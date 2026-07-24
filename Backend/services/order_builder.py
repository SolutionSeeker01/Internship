# order_builder.py - Order Builder Service
'use strict'

import hashlib
from decimal import Decimal
from typing import Dict, Any, Union, Optional

from models.execution_context import ExecutionContext
from models.execution_result import ExecutionResult, create_rejection_result
from models.order_quantity import OrderQuantity
from models.order_spec import OrderSpec
from utils.logger import get_logger

logger = get_logger(__name__)


def generate_idempotency_key(execution_target_id: int, signal_id: int, client_id: int) -> str:
    """
    Generates Layer 3 Idempotency Key per Section 7 of Architecture Reference:
    idempotency_key = SHA256(f"{execution_target_id}:{signal_id}:{client_id}")
    """
    raw_key = f"{execution_target_id}:{signal_id}:{client_id}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def build_order_spec(
    signal_data: Dict[str, Any],
    order_quantity: OrderQuantity,
    context: ExecutionContext,
    capabilities: Optional[Any] = None
) -> Union[OrderSpec, ExecutionResult]:
    """
    Translates signal parameters, order quantity, and execution context into a broker-agnostic OrderSpec.
    
    Implements Section 5.9 (Order Builder) of the Architecture Reference v1.3.
    
    Responsibilities:
      - Reads validated parameters from Signal, OrderQuantity, and ExecutionContext
      - Performs Layer 3 idempotency key generation (SHA256(target_id:signal_id:client_id))
      - Preserves explicit order_type, symbol, exchange, action, and product supplied
      - Inspects BrokerCapabilities before assembling order features
      - Returns immutable OrderSpec DTO on success
      - Returns ExecutionResult(outcome="RISK_REJECTED", fail_reason="UNSUPPORTED_ORDER_TYPE") if capability check fails
      
    Constraints:
      - NO margin validation (owned by Broker RMS / Dispatcher)
      - NO order_type mutation / inference (preserves explicit signal intent)
      - NO quantity calculation (owned by Quantity Calculator - Stage 4)
      - NO database queries or persistence
      - NO broker API calls or broker-specific payload translation
      - Pure deterministic assembly
    """
    symbol = str(signal_data.get("symbol", "")).upper().strip()
    action = str(signal_data.get("action", "")).upper().strip()
    quantity = int(order_quantity.quantity)

    # Resolve Exchange (explicit signal exchange > instrument_info exchange > default NSE)
    exchange = "NSE"
    if signal_data.get("exchange"):
        exchange = str(signal_data.get("exchange")).upper().strip()
    elif context and context.instrument_info and hasattr(context.instrument_info, "exchange"):
        exchange = str(context.instrument_info.exchange).upper().strip()

    # Resolve Entry / Limit Price
    price_val = signal_data.get("entry") or signal_data.get("price")
    price = Decimal(str(price_val)) if price_val is not None else None

    # Resolve Trigger Price
    trigger_val = signal_data.get("trigger_price") or signal_data.get("trigger")
    trigger_price = Decimal(str(trigger_val)) if trigger_val is not None else None

    # Preserve explicit Order Type (MARKET, LIMIT, SL, SL_MARKET) without mutation
    order_type = str(signal_data.get("order_type", "MARKET")).upper().strip()

    # Preserve explicit Product Type (MIS / INTRADAY, CNC / DELIVERY)
    product = str(signal_data.get("product", "MIS")).upper().strip()
    validity = str(signal_data.get("validity", "DAY")).upper().strip()

    # Check BrokerCapabilities if provided
    effective_caps = capabilities or getattr(context, "capabilities", None)
    if effective_caps:
        supported_types = getattr(effective_caps, "supported_order_types", None)
        if supported_types and order_type not in supported_types:
            logger.warning(f"Order Builder rejected: order_type '{order_type}' not supported by broker capabilities")
            return create_rejection_result(
                context,
                outcome="RISK_REJECTED",
                fail_reason="UNSUPPORTED_ORDER_TYPE",
                fail_category="PERMANENT"
            )

    # Compute Estimated Order Value for passive metadata
    est_price = price if price is not None else Decimal(str(signal_data.get("entry", "0")))
    estimated_value = Decimal(str(quantity)) * est_price

    # Layer 3 Idempotency Key Generation (Section 7)
    target_id = getattr(context, "execution_target_id", 0)
    signal_id = getattr(context, "signal_id", 0)
    client_id = getattr(context, "client_id", 0)
    idempotency_key = generate_idempotency_key(target_id, signal_id, client_id)

    return OrderSpec(
        symbol=symbol,
        exchange=exchange,
        action=action,
        quantity=quantity,
        order_type=order_type,
        product=product,
        validity=validity,
        price=price,
        trigger_price=trigger_price,
        idempotency_key=idempotency_key,
        estimated_value=estimated_value
    )
