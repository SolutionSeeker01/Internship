# Backend/models/child_order_spec.py
"""
ChildOrderSpec Passive DTO - Specification for Child Leg Orders (TP1, TP2, TP3, STOPLOSS)

Implements Section 5.15 of ARCHITECTURE_REFERENCE.md.
Represents a pure, immutable specification for a child leg order generated upon entry fill.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Dict, Any


@dataclass(frozen=True)
class ChildOrderSpec:
    """
    Pure DTO representing a child leg exit order specification.

    Fields:
        parent_order_id (int): Foreign key id of parent entry order.
        execution_target_id (int): Foreign key id of execution target.
        order_role (str): TARGET_1 | TARGET_2 | TARGET_3 | STOPLOSS.
        symbol (str): Trading symbol identifier.
        exchange (str): Target exchange (NSE, BSE, NFO, etc.).
        action (str): Opposite action of entry (e.g. SELL for BUY entry).
        quantity (int): Calculated split quantity.
        order_type (str): Strictly "LIMIT" per Section 5.15.
        price (Optional[Decimal]): Intended limit target price or trigger price.
        trigger_price (Optional[Decimal]): Trigger price for stop-loss orders.
        idempotency_key (str): SHA256(f"{parent_order_id}:{order_role}").
        broker (str): Target broker platform identifier.
    """
    parent_order_id: int
    execution_target_id: int
    order_role: str
    symbol: str
    exchange: str
    action: str
    quantity: int
    order_type: str
    price: Optional[Decimal]
    trigger_price: Optional[Decimal]
    idempotency_key: str
    broker: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parent_order_id": self.parent_order_id,
            "execution_target_id": self.execution_target_id,
            "order_role": self.order_role,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "price": float(self.price) if self.price is not None else None,
            "trigger_price": float(self.trigger_price) if self.trigger_price is not None else None,
            "idempotency_key": self.idempotency_key,
            "broker": self.broker
        }


@dataclass(frozen=True)
class ChildOrderSpecCollection:
    """
    Container DTO holding all generated child specifications for a filled entry.

    Fields:
        target_1 (Optional[ChildOrderSpec]): TP1 spec.
        target_2 (Optional[ChildOrderSpec]): TP2 spec.
        target_3 (Optional[ChildOrderSpec]): TP3 spec.
        stop_loss (ChildOrderSpec): Stop-Loss spec.
    """
    target_1: Optional[ChildOrderSpec]
    target_2: Optional[ChildOrderSpec]
    target_3: Optional[ChildOrderSpec]
    stop_loss: ChildOrderSpec

    def all_specs(self) -> List[ChildOrderSpec]:
        specs = []
        if self.target_1:
            specs.append(self.target_1)
        if self.target_2:
            specs.append(self.target_2)
        if self.target_3:
            specs.append(self.target_3)
        if self.stop_loss:
            specs.append(self.stop_loss)
        return specs
