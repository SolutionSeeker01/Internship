# Backend/services/order_manager/position_state_reconstructor.py
"""
Position State Reconstructor - Pure State Reconstruction Helper Module

Implements Section 5.15 Subsection 3 of ARCHITECTURE_REFERENCE.md (v1.5.3).
Provides deterministic, pure functions to reconstruct an open trade's in-memory
Order Manager position lifecycle state and active SL order details strictly from
persisted Trade and Order ORM records.

Constraints:
  - NO database writes or queries (takes pre-fetched Trade and Order objects/dicts)
  - NO broker API calls
  - NO state mutation (pure evaluation)
  - Strict compliance with Principles P1 (Single Responsibility) and P10 (Client Isolation)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Dict, Any
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReconstructedPositionState:
    """
    Pure immutable DTO carrying the reconstructed position lifecycle state for a trade.

    Fields:
        trade_id (int): Primary key ID of the trade.
        execution_target_id (int): Foreign key of execution target.
        position_state (str): PROTECTED | SL_CANCEL_PENDING | TARGET_ORDER_PENDING | PARTIALLY_PROTECTED | CLOSED
        remaining_quantity (int): Active un-exited open quantity Q_rem.
        active_sl_order_id (Optional[int]): Database primary key ID of currently active broker SL order.
        active_sl_broker_order_id (Optional[str]): Broker order ID string of active SL.
        active_sl_price (Optional[Decimal]): Intended limit/trigger price of active SL order.
        executed_targets (List[str]): List of executed target roles (e.g. ['TARGET_1']).
        trailing_sl_activated (bool): Persistent trailing stop activation flag.
    """
    trade_id: int
    execution_target_id: int
    position_state: str
    remaining_quantity: int
    active_sl_order_id: Optional[int]
    active_sl_broker_order_id: Optional[str]
    active_sl_price: Optional[Decimal]
    executed_targets: List[str]
    trailing_sl_activated: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "execution_target_id": self.execution_target_id,
            "position_state": self.position_state,
            "remaining_quantity": self.remaining_quantity,
            "active_sl_order_id": self.active_sl_order_id,
            "active_sl_broker_order_id": self.active_sl_broker_order_id,
            "active_sl_price": float(self.active_sl_price) if self.active_sl_price is not None else None,
            "executed_targets": self.executed_targets,
            "trailing_sl_activated": self.trailing_sl_activated
        }


def reconstruct_position_state(
    trade_id: int,
    execution_target_id: int,
    entry_filled_qty: int,
    trade_status: str,
    trailing_sl_activated: bool,
    child_orders: List[Dict[str, Any]]
) -> ReconstructedPositionState:
    """
    Deterministically reconstructs a trade's in-memory position state from persisted records.

    Section 5.15 Subsection 3 State Rules:
      - CLOSED: trade_status == 'CLOSED' or remaining_quantity == 0
      - TARGET_ORDER_PENDING: Any child TARGET order has status in ('PLACED', 'SUBMITTED', 'PENDING')
      - SL_CANCEL_PENDING: Active child SL order has status in ('CANCEL_REQUESTED', 'PENDING_CANCEL')
      - PARTIALLY_PROTECTED: Partial target filled (TP1/TP2 executed) and active SL order exists for Q_rem
      - PROTECTED: Entry filled, no targets executed yet, and active SL order covers full entry Q

    Args:
        trade_id (int): Primary key ID of trade.
        execution_target_id (int): Execution target ID.
        entry_filled_qty (int): Total filled entry quantity Q.
        trade_status (str): Database status string (OPEN, PARTIALLY_CLOSED, CLOSED).
        trailing_sl_activated (bool): Persistent flag from trades.trailing_sl_activated.
        child_orders (List[Dict[str, Any]]): List of child order dictionaries. Each dict should contain:
            id, order_role, status, quantity, filled_quantity, price, trigger_price, broker_order_id.

    Returns:
        ReconstructedPositionState: Immutable DTO carrying reconstructed state.
    """
    if entry_filled_qty <= 0:
        raise ValueError(f"Invalid entry_filled_qty: {entry_filled_qty}. Must be > 0.")

    # 1. Inspect Child Target Orders
    executed_targets: List[str] = []
    target_order_pending = False
    executed_target_qty = 0

    for order in child_orders:
        role = str(order.get("order_role", "")).upper()
        status = str(order.get("status", "")).upper()

        if role in ("TARGET_1", "TARGET_2", "TARGET_3"):
            if status in ("COMPLETE", "FILLED"):
                executed_targets.append(role)
                executed_qty = int(order.get("filled_quantity") or order.get("quantity") or 0)
                executed_target_qty += executed_qty
            elif status in ("PLACED", "SUBMITTED", "PENDING"):
                target_order_pending = True

    # Calculate remaining un-exited open quantity Q_rem
    remaining_quantity = max(0, entry_filled_qty - executed_target_qty)

    # 2. Inspect Child Stop-Loss Orders
    active_sl_id: Optional[int] = None
    active_sl_broker_id: Optional[str] = None
    active_sl_price: Optional[Decimal] = None
    sl_cancel_pending = False

    for order in child_orders:
        role = str(order.get("order_role", "")).upper()
        status = str(order.get("status", "")).upper()

        if role == "STOPLOSS":
            if status in ("OPEN", "SUBMITTED", "PLACED"):
                active_sl_id = int(order.get("id")) if order.get("id") is not None else None
                active_sl_broker_id = order.get("broker_order_id")
                
                # Get price preference: price or trigger_price
                price_val = order.get("trigger_price") or order.get("price")
                active_sl_price = Decimal(str(price_val)) if price_val is not None else None
            elif status in ("CANCEL_REQUESTED", "PENDING_CANCEL"):
                sl_cancel_pending = True

    # 3. Resolve Position State per Section 5.15 Subsection 3
    if trade_status.upper() == "CLOSED" or remaining_quantity == 0:
        resolved_state = "CLOSED"
        remaining_quantity = 0
    elif target_order_pending:
        resolved_state = "TARGET_ORDER_PENDING"
    elif sl_cancel_pending:
        resolved_state = "SL_CANCEL_PENDING"
    elif executed_targets or trade_status.upper() == "PARTIALLY_CLOSED":
        resolved_state = "PARTIALLY_PROTECTED"
    else:
        resolved_state = "PROTECTED"

    return ReconstructedPositionState(
        trade_id=trade_id,
        execution_target_id=execution_target_id,
        position_state=resolved_state,
        remaining_quantity=remaining_quantity,
        active_sl_order_id=active_sl_id,
        active_sl_broker_order_id=active_sl_broker_id,
        active_sl_price=active_sl_price,
        executed_targets=sorted(executed_targets),
        trailing_sl_activated=trailing_sl_activated
    )
