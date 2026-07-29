# Backend/services/order_manager/child_order_builder.py
"""
Child Order Builder - Pure Side-Effect-Free Child Order Specification Generator

Implements Section 5.15 of ARCHITECTURE_REFERENCE.md (v1.4).
Calculates target split quantities and constructs immutable ChildOrderSpec objects.
"""

import hashlib
import math
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from models.child_order_spec import ChildOrderSpec, ChildOrderSpecCollection
from utils.logger import get_logger

logger = get_logger(__name__)


def calculate_target_split_quantities(filled_quantity: int) -> Tuple[int, int, int]:
    """
    Calculates target split quantities strictly per Section 5.15:
      - TP1 = floor(Q * 0.50)
      - TP2 = floor(Q * 0.25)
      - TP3 = Q - (TP1 + TP2)

    Args:
        filled_quantity (int): Total filled entry quantity Q.

    Returns:
        Tuple[int, int, int]: (tp1_qty, tp2_qty, tp3_qty)

    Raises:
        ValueError: If filled_quantity is not a positive integer (> 0).
    """
    if not isinstance(filled_quantity, int) or isinstance(filled_quantity, bool):
        raise ValueError(f"Invalid filled_quantity: must be an integer, got {type(filled_quantity).__name__}")

    if filled_quantity <= 0:
        raise ValueError(f"Invalid filled_quantity {filled_quantity}: must be strictly greater than 0")

    tp1_qty = math.floor(filled_quantity * 0.50)
    tp2_qty = math.floor(filled_quantity * 0.25)
    tp3_qty = filled_quantity - (tp1_qty + tp2_qty)

    return tp1_qty, tp2_qty, tp3_qty


def generate_child_idempotency_key(parent_order_id: int, order_role: str) -> str:
    """
    Generates deterministic Layer 3 child order idempotency key per approved specification:
    child_idempotency_key = SHA256(f"{parent_order_id}:{order_role}")

    Args:
        parent_order_id (int): Parent entry order primary key ID.
        order_role (str): TARGET_1 | TARGET_2 | TARGET_3 | STOPLOSS.

    Returns:
        str: 64-character SHA256 hex string.
    """
    raw_key = f"{parent_order_id}:{order_role}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def build_child_order_specs(
    parent_order_id: int,
    execution_target_id: int,
    filled_quantity: int,
    entry_action: str,
    symbol: str,
    exchange: str,
    broker: str,
    stoploss_price: Decimal,
    t1_price: Optional[Decimal] = None,
    t2_price: Optional[Decimal] = None,
    t3_price: Optional[Decimal] = None
) -> ChildOrderSpecCollection:
    """
    Constructs pure ChildOrderSpec DTOs for a filled entry order.

    Strict Architectural Mandates (Section 5.15):
      1. order_type = "LIMIT" for ALL child exit specs (no market exits).
      2. Quantities split as 50% TP1, 25% TP2 (floor), remaining TP3.
      3. Action is opposite of entry (BUY entry -> SELL exit; SELL entry -> BUY exit).
      4. Idempotency key = SHA256(f"{parent_order_id}:{order_role}").

    Args:
        parent_order_id (int): Parent entry order ID.
        execution_target_id (int): Execution target ID.
        filled_quantity (int): Total filled entry quantity Q.
        entry_action (str): BUY or SELL.
        symbol (str): Trading symbol.
        exchange (str): Exchange identifier (NSE, BSE, etc.).
        broker (str): Broker platform identifier.
        stoploss_price (Decimal): Pre-computed stop-loss price.
        t1_price (Optional[Decimal]): Pre-computed T1 price.
        t2_price (Optional[Decimal]): Pre-computed T2 price.
        t3_price (Optional[Decimal]): Pre-computed T3 price.

    Returns:
        ChildOrderSpecCollection: Container holding target_1, target_2, target_3, and stop_loss specs.

    Raises:
        ValueError: If stoploss_price is missing/invalid or filled_quantity <= 0.
    """
    if stoploss_price is None or not isinstance(stoploss_price, (Decimal, int, float)) or Decimal(str(stoploss_price)) <= 0:
        raise ValueError(f"Invalid stoploss_price: {stoploss_price}. Stoploss price is mandatory.")

    stoploss_price = Decimal(str(stoploss_price))
    
    # Opposite action for exits
    exit_action = "SELL" if entry_action.upper() == "BUY" else "BUY"

    # Calculate split quantities
    tp1_qty, tp2_qty, tp3_qty = calculate_target_split_quantities(filled_quantity)

    # 1. TARGET_1 Spec
    t1_spec: Optional[ChildOrderSpec] = None
    if tp1_qty > 0 and t1_price is not None:
        t1_spec = ChildOrderSpec(
            parent_order_id=parent_order_id,
            execution_target_id=execution_target_id,
            order_role="TARGET_1",
            symbol=symbol,
            exchange=exchange,
            action=exit_action,
            quantity=tp1_qty,
            order_type="LIMIT",
            price=Decimal(str(t1_price)),
            trigger_price=None,
            idempotency_key=generate_child_idempotency_key(parent_order_id, "TARGET_1"),
            broker=broker
        )

    # 2. TARGET_2 Spec
    t2_spec: Optional[ChildOrderSpec] = None
    if tp2_qty > 0 and t2_price is not None:
        t2_spec = ChildOrderSpec(
            parent_order_id=parent_order_id,
            execution_target_id=execution_target_id,
            order_role="TARGET_2",
            symbol=symbol,
            exchange=exchange,
            action=exit_action,
            quantity=tp2_qty,
            order_type="LIMIT",
            price=Decimal(str(t2_price)),
            trigger_price=None,
            idempotency_key=generate_child_idempotency_key(parent_order_id, "TARGET_2"),
            broker=broker
        )

    # 3. TARGET_3 Spec
    t3_spec: Optional[ChildOrderSpec] = None
    if tp3_qty > 0 and t3_price is not None:
        t3_spec = ChildOrderSpec(
            parent_order_id=parent_order_id,
            execution_target_id=execution_target_id,
            order_role="TARGET_3",
            symbol=symbol,
            exchange=exchange,
            action=exit_action,
            quantity=tp3_qty,
            order_type="LIMIT",
            price=Decimal(str(t3_price)),
            trigger_price=None,
            idempotency_key=generate_child_idempotency_key(parent_order_id, "TARGET_3"),
            broker=broker
        )

    # 4. STOPLOSS Spec (Covers total filled quantity Q upon entry fill)
    # Apply 5% execution buffer between trigger_price and limit price for guaranteed broker execution
    # For SELL exit (exiting BUY entry): limit_price is 5% below SL trigger_price
    # For BUY exit (exiting SELL entry): limit_price is 5% above SL trigger_price
    from utils.tick_size import normalize_tick_size
    buffer_pct = Decimal("0.05")
    is_sell_exit = (exit_action.upper() == "SELL")
    raw_limit_sl = stoploss_price * (Decimal("1") - buffer_pct) if is_sell_exit else stoploss_price * (Decimal("1") + buffer_pct)
    limit_sl_price = normalize_tick_size(raw_limit_sl)

    sl_spec = ChildOrderSpec(
        parent_order_id=parent_order_id,
        execution_target_id=execution_target_id,
        order_role="STOPLOSS",
        symbol=symbol,
        exchange=exchange,
        action=exit_action,
        quantity=filled_quantity,
        order_type="LIMIT",
        price=limit_sl_price,
        trigger_price=stoploss_price,
        idempotency_key=generate_child_idempotency_key(parent_order_id, "STOPLOSS"),
        broker=broker
    )

    return ChildOrderSpecCollection(
        target_1=t1_spec,
        target_2=t2_spec,
        target_3=t3_spec,
        stop_loss=sl_spec
    )
