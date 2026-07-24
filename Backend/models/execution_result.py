# execution_result.py - Passive ExecutionResult DTO & Rejection Factory
'use strict'

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Any



@dataclass(frozen=True)
class ExecutionResult:
    """
    Carry the complete outcome of a Trade Engine execution attempt as an immutable,
    serializable data object.
    
    Implements Section 5.12 (ExecutionResult) of the Architecture Reference.
    """
    execution_target_id: int
    signal_id: int
    client_id: int
    outcome: str
    broker_order_id: Optional[str] = None
    fail_reason: Optional[str] = None
    fail_category: Optional[str] = None
    retryable: bool = False
    quantity: Optional[int] = None
    executed_price: Optional[Decimal] = None
    order_type: Optional[str] = None
    idempotency_key: str = ""
    executed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "execution_target_id": self.execution_target_id,
            "signal_id": self.signal_id,
            "client_id": self.client_id,
            "outcome": self.outcome,
            "broker_order_id": self.broker_order_id,
            "fail_reason": self.fail_reason,
            "fail_category": self.fail_category,
            "retryable": self.retryable,
            "quantity": self.quantity,
            "executed_price": float(self.executed_price) if self.executed_price is not None else None,
            "order_type": self.order_type,
            "idempotency_key": self.idempotency_key,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None
        }


def create_rejection_result(
    context: Any,
    outcome: str,
    fail_reason: str,
    fail_category: str = "PERMANENT",
    retryable: bool = False
) -> ExecutionResult:
    """
    Centralized factory for creating standardized rejection ExecutionResult DTOs
    from an ExecutionContext instance.
    """
    target_id = getattr(context, "execution_target_id", 0)
    signal_id = getattr(context, "signal_id", 0)
    client_id = getattr(context, "client_id", 0)
    
    return ExecutionResult(
        execution_target_id=target_id,
        signal_id=signal_id,
        client_id=client_id,
        outcome=outcome,
        fail_reason=fail_reason,
        fail_category=fail_category,
        retryable=retryable,
        executed_at=datetime.now()
    )
