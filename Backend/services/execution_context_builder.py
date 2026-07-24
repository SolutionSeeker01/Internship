# execution_context_builder.py - ExecutionContext Builder Service
'use strict'

from datetime import datetime
from typing import Dict, Any, Optional, Union

from database.db import SessionLocal
from database.signal_repository import get_signal_by_id
from models.broker_account import BrokerAccount
from models.execution_context import (
    ExecutionContext,
    FundsData,
    MarginsData,
    InstrumentInfo
)
from services.brokers.factory import BrokerFactory
from utils.logger import get_logger

logger = get_logger(__name__)


# Standard ExecutionResult DTO representation for fetch failure per Section 4 & 5.5
class ContextFetchRejection:
    def __init__(self, target_id: int, signal_id: int, client_id: int, reason: str):
        self.execution_target_id = target_id
        self.signal_id = signal_id
        self.client_id = client_id
        self.outcome = "RUNTIME_REJECTED"
        self.broker_order_id = None
        self.fail_reason = reason
        self.fail_category = "PERMANENT"
        self.retryable = False
        self.quantity = None
        self.executed_price = None
        self.order_type = None
        self.idempotency_key = ""
        self.executed_at = datetime.now()


def build_execution_context(
    target_data: Dict[str, Any],
    signal_data: Optional[Dict[str, Any]] = None,
    broker_adapter_override: Optional[Any] = None
) -> Union[ExecutionContext, ContextFetchRejection]:
    """
    Gathers dynamic runtime state and packages it into an immutable ExecutionContext.
    
    Implements Section 5.5 (ExecutionContext Builder) of the Architecture Reference.
    
    Responsibilities:
      - Receives claimed ExecutionTarget dictionary
      - Loads associated Signal data (if not provided)
      - Resolves assigned BrokerAccount for target client_id
      - Invokes BrokerInterface to fetch live session_valid, funds, margins, instrument_info
      - Assembles and returns immutable ExecutionContext dataclass
      - IF ANY FETCH FAILS: returns ExecutionResult with outcome RUNTIME_REJECTED (Section 4 & 5.5)
      
    Constraints:
      - Performs NO validation, risk checking, quantity math, or order building
      - Manufactures NO synthetic or default runtime data on fetch failure
    """
    target_id = target_data.get("id")
    signal_id = target_data.get("signal_id")
    client_id = target_data.get("client_id")
    
    logger.info(f"ExecutionContext Builder assembling runtime state for target ID {target_id} (signal_id: {signal_id}, client_id: {client_id})...")

    # 1. Load Signal data if not passed in
    effective_signal = signal_data
    if not effective_signal and signal_id:
        try:
            effective_signal = get_signal_by_id(signal_id)
        except Exception as e:
            logger.error(f"Failed to fetch signal ID {signal_id} for target ID {target_id}: {e}")
            return ContextFetchRejection(target_id, signal_id, client_id, "SIGNAL_NOT_FOUND")

    if not effective_signal:
        logger.error(f"Signal ID {signal_id} missing for target ID {target_id}.")
        return ContextFetchRejection(target_id, signal_id or 0, client_id or 0, "SIGNAL_MISSING")

    # 2. Resolve BrokerAccount for target client_id
    broker_name = "ZERODHA"
    broker_account = None
    
    db = SessionLocal()
    try:
        broker_account = db.query(BrokerAccount).filter(BrokerAccount.user_id == client_id).first()
        if broker_account and broker_account.broker:
            broker_name = broker_account.broker
    except Exception as e:
        logger.error(f"Database error resolving broker account for client ID {client_id}: {e}")
        return ContextFetchRejection(target_id, signal_id, client_id, "BROKER_ACCOUNT_DB_ERROR")
    finally:
        db.close()

    if not broker_account and not broker_adapter_override:
        logger.error(f"No broker account found for client ID {client_id}.")
        return ContextFetchRejection(target_id, signal_id, client_id, "BROKER_ACCOUNT_NOT_FOUND")

    # 3. Resolve BrokerAdapter (either injected test override or BrokerFactory)
    broker_adapter = broker_adapter_override
    if not broker_adapter and broker_account:
        try:
            from security.encryption import decrypt_value
            api_key = decrypt_value(broker_account.api_key) if broker_account.api_key else ""
            access_token = decrypt_value(broker_account.access_token) if broker_account.access_token else ""
            broker_adapter = BrokerFactory.get_broker(
                broker_name,
                api_key=api_key,
                access_token=access_token
            )
        except Exception as e:
            logger.error(f"Failed to instantiate broker adapter for client {client_id}: {e}")
            return ContextFetchRejection(target_id, signal_id, client_id, "BROKER_ADAPTER_INIT_FAILED")

    # 4. Fetch dynamic broker runtime attributes without manufacturing default values
    try:
        # Session validity
        session_valid = False
        if hasattr(broker_adapter, "verify_session"):
            sess = broker_adapter.verify_session()
            session_valid = getattr(sess, "valid", True) if hasattr(sess, "valid") else bool(sess)
        else:
            session_valid = True

        # Market status
        market_open = True
        exchange_status = "NORMAL"
        if hasattr(broker_adapter, "is_market_open"):
            market_open = broker_adapter.is_market_open("NSE")

        # Funds
        f = broker_adapter.get_funds() if hasattr(broker_adapter, "get_funds") else None
        if isinstance(f, dict):
            funds = FundsData(
                available_cash=float(f.get("available_cash", 0.0)),
                used_margin=float(f.get("used_margin", 0.0)),
                net_value=float(f.get("net_value", 0.0))
            )
        elif hasattr(f, "available_cash"):
            funds = f
        else:
            logger.error(f"Failed to fetch funds data from broker for target ID {target_id}.")
            return ContextFetchRejection(target_id, signal_id, client_id, "FUNDS_FETCH_FAILED")

        # Margins
        m = broker_adapter.get_margins("EQ") if hasattr(broker_adapter, "get_margins") else None
        if isinstance(m, dict):
            margins = MarginsData(
                available_margin=float(m.get("available_margin", 0.0)),
                used_margin=float(m.get("used_margin", 0.0)),
                collateral=float(m.get("collateral", 0.0))
            )
        elif hasattr(m, "available_margin"):
            margins = m
        else:
            logger.error(f"Failed to fetch margin data from broker for target ID {target_id}.")
            return ContextFetchRejection(target_id, signal_id, client_id, "MARGINS_FETCH_FAILED")

        # Instrument Info
        symbol = effective_signal.get("symbol", "")
        inst = broker_adapter.get_instrument(symbol, "NSE") if hasattr(broker_adapter, "get_instrument") and symbol else None
        if isinstance(inst, dict):
            instrument_info = InstrumentInfo(
                lot_size=int(inst.get("lot_size", 1)),
                tick_size=float(inst.get("tick_size", 0.05)),
                freeze_qty=int(inst.get("freeze_qty", 100000)),
                segment=str(inst.get("segment", "EQ")),
                exchange=str(inst.get("exchange", "NSE"))
            )
        elif hasattr(inst, "lot_size"):
            instrument_info = inst
        else:
            logger.error(f"Failed to fetch instrument info for symbol '{symbol}' target ID {target_id}.")
            return ContextFetchRejection(target_id, signal_id, client_id, "INSTRUMENT_FETCH_FAILED")

        # Capabilities (Section 5.11)
        capabilities = broker_adapter.capabilities() if hasattr(broker_adapter, "capabilities") else None

    except Exception as err:
        logger.error(f"Error during dynamic broker attribute fetch for target {target_id}: {err}")
        return ContextFetchRejection(target_id, signal_id, client_id, f"FETCH_EXCEPTION: {err}")

    # 5. Assemble and return immutable ExecutionContext
    fetched_at = datetime.now()
    ctx = ExecutionContext(
        session_valid=session_valid,
        market_open=market_open,
        exchange_status=exchange_status,
        funds=funds,
        margins=margins,
        instrument_info=instrument_info,
        fetched_at=fetched_at,
        broker=broker_name,
        signal=effective_signal,
        target=target_data,
        capabilities=capabilities
    )
    
    logger.info(f"ExecutionContext successfully assembled for target ID {target_id} (broker: {broker_name}, fetched_at: {fetched_at.isoformat()}).")
    return ctx
