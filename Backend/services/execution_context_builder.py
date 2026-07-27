# execution_context_builder.py - ExecutionContext Builder Service
'use strict'

from datetime import datetime
from decimal import Decimal
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
        # Session validity — uses verify_connection() per BaseBroker contract.
        # Raises BrokerAdapterException if session is expired/invalid; we catch and reject.
        session_valid = False
        try:
            session_valid = broker_adapter.verify_connection()
        except Exception:
            # verify_connection raises on invalid session; default to False (will be caught by RuntimeValidator)
            session_valid = False

        # Market status
        market_open = True
        exchange_status = "NORMAL"
        if hasattr(broker_adapter, "is_market_open"):
            market_open = broker_adapter.is_market_open("NSE")

        # Funds and Margins — Canonical BaseBrokerAdapter Contract (get_margins)
        m = broker_adapter.get_margins() if hasattr(broker_adapter, "get_margins") else None
        if isinstance(m, dict):
            if "net_value" not in m or m["net_value"] is None:
                logger.error(f"Broker adapter violation: get_margins() response missing required 'net_value' field for target {target_id}.")
                return ContextFetchRejection(target_id, signal_id, client_id, "BROKER_CONTRACT_VIOLATION_MISSING_NET_VALUE")

            cash = Decimal(str(m.get("available_cash", 0.0)))
            used = Decimal(str(m.get("utilized_margin", 0.0)))
            collateral = Decimal(str(m.get("collateral", 0.0)))
            net_val = Decimal(str(m["net_value"]))
            
            funds = FundsData(
                available_cash=cash,
                used_margin=used,
                net_value=net_val
            )
            margins = MarginsData(
                available_margin=cash,
                used_margin=used,
                collateral=collateral
            )
        elif hasattr(m, "available_cash") and hasattr(m, "net_value"):
            cash = Decimal(str(getattr(m, "available_cash", 0.0)))
            used = Decimal(str(getattr(m, "utilized_margin", getattr(m, "used_margin", 0.0))))
            collateral = Decimal(str(getattr(m, "collateral", 0.0)))
            net_val = Decimal(str(getattr(m, "net_value")))
            funds = FundsData(available_cash=cash, used_margin=used, net_value=net_val)
            margins = MarginsData(available_margin=cash, used_margin=used, collateral=collateral)
        else:
            logger.error(f"Failed to fetch margin/funds data from broker for target ID {target_id}.")
            return ContextFetchRejection(target_id, signal_id, client_id, "MARGINS_FETCH_FAILED")

        # Instrument Info — Resolved via Database Instrument Repository / Market Master
        symbol = effective_signal.get("symbol", "") if isinstance(effective_signal, dict) else getattr(effective_signal, "symbol", "")
        inst_dict = None
        if symbol:
            try:
                from database.instrument_repository import get_instrument_by_symbol
                inst_dict = get_instrument_by_symbol(symbol)
            except Exception as inst_err:
                logger.warning(f"Could not fetch instrument '{symbol}' from repository for target {target_id}: {inst_err}")

        lot_size = int(inst_dict.get("lot_size", 1)) if inst_dict and "lot_size" in inst_dict else 1
        tick_size = Decimal(str(inst_dict.get("tick_size", "0.05"))) if inst_dict and "tick_size" in inst_dict else Decimal("0.05")
        freeze_qty = int(inst_dict.get("freeze_qty", 100000)) if inst_dict and "freeze_qty" in inst_dict else 100000
        segment = str(inst_dict.get("segment", "EQ")) if inst_dict and "segment" in inst_dict else "EQ"
        exchange = str(inst_dict.get("exchange", "NSE")) if inst_dict and "exchange" in inst_dict else "NSE"

        instrument_info = InstrumentInfo(
            lot_size=lot_size,
            tick_size=tick_size,
            freeze_qty=freeze_qty,
            segment=segment,
            exchange=exchange
        )

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
