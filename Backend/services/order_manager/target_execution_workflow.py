# Backend/services/order_manager/target_execution_workflow.py
"""
Target Execution Workflow - Pure Workflow Planning Engine

Implements Section 5.15 Subsection 4 of ARCHITECTURE_REFERENCE.md (v1.5.3).
Evaluates triggering market/broker events against the reconstructed position state
and outputs an immutable, passive WorkflowPlan DTO detailing the exact sequential
execution steps (Cancel SL -> Await Confirmation -> Place Target LIMIT -> Protect Q_rem).

Constraints:
  - NO BrokerInterface calls
  - NO database writes or repository access
  - NO HTTP or network calls
  - NO state mutation
  - Pure, deterministic business planning engine (Principle P2 & P5)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from models.child_order_spec import ChildOrderSpec
from services.order_manager.position_state_reconstructor import ReconstructedPositionState
from utils.logger import get_logger

logger = get_logger(__name__)

# Temporary business rule.
# TODO: Confirm final value with business (currently 5%; may change to 6% or become configurable).
LIMIT_PRICE_BUFFER_PCT = Decimal("0.05")



@dataclass(frozen=True)
class WorkflowStep:
    """
    Immutable representation of a single atomic action within a workflow plan.

    Step Types:
        - CANCEL_SL: Cancel active broker Stop-Loss order.
        - AWAIT_CANCEL_CONFIRMATION: Wait for broker cancellation response.
        - PLACE_TARGET_LIMIT: Submit LIMIT exit order for target quantity.
        - AWAIT_FILL_CONFIRMATION: Wait for target fill.
        - PLACE_SAFETY_SL: Place new Stop-Loss limit order for remaining quantity Q_rem.
        - CLOSE_TRADE: Mark trade CLOSED and finalize accounting.

    Fields:
        step_number (int): Sequential execution order (1-indexed).
        action_type (str): Action classification.
        target_role (Optional[str]): TARGET_1 | TARGET_2 | TARGET_3 | STOPLOSS | TRAILING_SL.
        target_quantity (int): Quantity associated with this step.
        target_price (Optional[Decimal]): Limit/trigger price if applicable.
        cancel_order_id (Optional[int]): DB primary key ID of order to cancel.
        cancel_broker_order_id (Optional[str]): Broker order ID to cancel.
        order_spec (Optional[ChildOrderSpec]): Pure spec for new order placement.
    """
    step_number: int
    action_type: str
    target_role: Optional[str]
    target_quantity: int
    target_price: Optional[Decimal]
    cancel_order_id: Optional[int]
    cancel_broker_order_id: Optional[str]
    order_spec: Optional[ChildOrderSpec]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action_type": self.action_type,
            "target_role": self.target_role,
            "target_quantity": self.target_quantity,
            "target_price": float(self.target_price) if self.target_price is not None else None,
            "cancel_order_id": self.cancel_order_id,
            "cancel_broker_order_id": self.cancel_broker_order_id,
            "order_spec": self.order_spec.to_dict() if self.order_spec else None
        }


@dataclass(frozen=True)
class WorkflowPlan:
    """
    Immutable DTO representing the complete sequential workflow plan for a trigger event.

    Fields:
        trade_id (int): Primary key ID of the trade.
        trigger_event (str): TP1_HIT | TP2_HIT | TP3_HIT | SL_HIT | TRAILING_SL_HIT | INVALID_TRIGGER.
        current_position_state (str): Position state before workflow execution.
        expected_next_position_state (str): Expected position state after successful workflow completion.
        steps (List[WorkflowStep]): Ordered list of execution steps.
        remaining_quantity_after_workflow (int): Expected Q_rem after workflow executes.
        is_valid (bool): True if workflow plan is valid, False if rejected/ignored.
        rejection_reason (Optional[str]): Human-readable reason if workflow plan is invalid.
    """
    trade_id: int
    trigger_event: str
    current_position_state: str
    expected_next_position_state: str
    steps: List[WorkflowStep]
    remaining_quantity_after_workflow: int
    is_valid: bool
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "trigger_event": self.trigger_event,
            "current_position_state": self.current_position_state,
            "expected_next_position_state": self.expected_next_position_state,
            "steps": [s.to_dict() for s in self.steps],
            "remaining_quantity_after_workflow": self.remaining_quantity_after_workflow,
            "is_valid": self.is_valid,
            "rejection_reason": self.rejection_reason
        }


def plan_target_execution_workflow(
    state: ReconstructedPositionState,
    trigger_event: str,
    target_quantity: int,
    target_price: Decimal,
    parent_order_id: int,
    symbol: str,
    exchange: str,
    broker: str,
    entry_action: str,
    stoploss_price: Decimal
) -> WorkflowPlan:
    """
    Evaluates a trigger event against the trade's current state and produces an immutable WorkflowPlan.

    Section 5.15 Subsection 4 Sequential Workflow:
      1. Cancel active Stop-Loss order (if present).
      2. Await cancellation confirmation.
      3. Place Target LIMIT exit order for target_quantity.
      4. Await target fill.
      5. If Q_rem > 0: Place new STOPLOSS limit order for Q_rem.
         If Q_rem == 0: Mark trade CLOSED.

    Args:
        state (ReconstructedPositionState): Current reconstructed position state.
        trigger_event (str): TP1_HIT | TP2_HIT | TP3_HIT | SL_HIT | TRAILING_SL_HIT.
        target_quantity (int): Target quantity to exit.
        target_price (Decimal): Exit target price.
        parent_order_id (int): Parent entry order ID.
        symbol (str): Trading symbol.
        exchange (str): Exchange.
        broker (str): Broker platform.
        entry_action (str): BUY or SELL.
        stoploss_price (Decimal): Constant original stoploss price for replacement SL.

    Returns:
        WorkflowPlan: Immutable DTO containing step-by-step execution pipeline.
    """
    event = str(trigger_event).upper().strip()
    exit_action = "SELL" if entry_action.upper() == "BUY" else "BUY"
    target_price = Decimal(str(target_price))
    stoploss_price = Decimal(str(stoploss_price))

    # Single multiplier calculation to avoid duplicate logic across BUY/SELL exit actions
    # BUY trade (SELL exit): accept price down to 5% below trigger  → multiplier = 1 - 0.05 = 0.95
    # SELL trade (BUY exit): accept price up to 5% above trigger   → multiplier = 1 + 0.05 = 1.05
    multiplier = (
        Decimal("1") - LIMIT_PRICE_BUFFER_PCT
        if exit_action == "SELL"
        else Decimal("1") + LIMIT_PRICE_BUFFER_PCT
    )

    limit_exit_price = target_price * multiplier
    limit_sl_price = stoploss_price * multiplier

    # Rejection Check 1: Trade already closed
    if state.position_state == "CLOSED" or state.remaining_quantity <= 0:
        return WorkflowPlan(
            trade_id=state.trade_id,
            trigger_event=event,
            current_position_state=state.position_state,
            expected_next_position_state="CLOSED",
            steps=[],
            remaining_quantity_after_workflow=0,
            is_valid=False,
            rejection_reason="Trade is already CLOSED or remaining quantity is 0."
        )

    # Rejection Check 2: In-flight workflow lock (state is transition pending)
    if state.position_state in ("SL_CANCEL_PENDING", "TARGET_ORDER_PENDING"):
        return WorkflowPlan(
            trade_id=state.trade_id,
            trigger_event=event,
            current_position_state=state.position_state,
            expected_next_position_state=state.position_state,
            steps=[],
            remaining_quantity_after_workflow=state.remaining_quantity,
            is_valid=False,
            rejection_reason=f"Workflow transition already in progress: '{state.position_state}'."
        )

    # Rejection Check 3: Duplicate target execution check
    role_map = {"TP1_HIT": "TARGET_1", "TP2_HIT": "TARGET_2", "TP3_HIT": "TARGET_3"}
    target_role = role_map.get(event)
    if target_role and target_role in state.executed_targets:
        return WorkflowPlan(
            trade_id=state.trade_id,
            trigger_event=event,
            current_position_state=state.position_state,
            expected_next_position_state=state.position_state,
            steps=[],
            remaining_quantity_after_workflow=state.remaining_quantity,
            is_valid=False,
            rejection_reason=f"Duplicate execution attempt: target '{target_role}' has already executed."
        )

    # Determine effective exit quantity and expected remaining quantity
    effective_exit_qty = min(target_quantity, state.remaining_quantity)
    new_remaining_qty = max(0, state.remaining_quantity - effective_exit_qty)

    steps: List[WorkflowStep] = []
    step_counter = 1

    # Step 1: Cancel active Stop-Loss order (if present at broker)
    if state.active_sl_order_id is not None or state.active_sl_broker_order_id is not None:
        steps.append(WorkflowStep(
            step_number=step_counter,
            action_type="CANCEL_SL",
            target_role="STOPLOSS",
            target_quantity=state.remaining_quantity,
            target_price=state.active_sl_price,
            cancel_order_id=state.active_sl_order_id,
            cancel_broker_order_id=state.active_sl_broker_order_id,
            order_spec=None
        ))
        step_counter += 1

        steps.append(WorkflowStep(
            step_number=step_counter,
            action_type="AWAIT_CANCEL_CONFIRMATION",
            target_role="STOPLOSS",
            target_quantity=state.remaining_quantity,
            target_price=None,
            cancel_order_id=state.active_sl_order_id,
            cancel_broker_order_id=state.active_sl_broker_order_id,
            order_spec=None
        ))
        step_counter += 1

    # Step 2: Build ChildOrderSpec for the exit order (Target or Full SL Exit)
    assigned_role = target_role if target_role else ("STOPLOSS" if "SL" in event else "EXIT_ALL")
    
    # Generate deterministic child idempotency key: SHA256(f"{parent_order_id}:{assigned_role}")
    import hashlib
    idempotency_key = hashlib.sha256(f"{parent_order_id}:{assigned_role}".encode("utf-8")).hexdigest()

    exit_spec = ChildOrderSpec(
        parent_order_id=parent_order_id,
        execution_target_id=state.execution_target_id,
        order_role=assigned_role,
        symbol=symbol,
        exchange=exchange,
        action=exit_action,
        quantity=effective_exit_qty,
        order_type="LIMIT",
        price=limit_exit_price,          # 5% threshold applied for guaranteed fill
        trigger_price=target_price if "SL" in event else None,  # trigger stays at actual price
        idempotency_key=idempotency_key,
        broker=broker
    )

    steps.append(WorkflowStep(
        step_number=step_counter,
        action_type="PLACE_TARGET_LIMIT",
        target_role=assigned_role,
        target_quantity=effective_exit_qty,
        target_price=target_price,
        cancel_order_id=None,
        cancel_broker_order_id=None,
        order_spec=exit_spec
    ))
    step_counter += 1

    steps.append(WorkflowStep(
        step_number=step_counter,
        action_type="AWAIT_FILL_CONFIRMATION",
        target_role=assigned_role,
        target_quantity=effective_exit_qty,
        target_price=target_price,
        cancel_order_id=None,
        cancel_broker_order_id=None,
        order_spec=None
    ))
    step_counter += 1

    # Step 3: Handle Post-Fill Safety Order or Trade Closure
    if new_remaining_qty > 0:
        sl_idempotency_key = hashlib.sha256(f"{parent_order_id}:STOPLOSS_REPLACEMENT_{new_remaining_qty}".encode("utf-8")).hexdigest()
        replacement_sl_spec = ChildOrderSpec(
            parent_order_id=parent_order_id,
            execution_target_id=state.execution_target_id,
            order_role="STOPLOSS",
            symbol=symbol,
            exchange=exchange,
            action=exit_action,
            quantity=new_remaining_qty,
            order_type="LIMIT",
            price=limit_sl_price,            # 5% threshold applied for guaranteed fill
            trigger_price=stoploss_price,    # trigger stays at actual SL price
            idempotency_key=sl_idempotency_key,
            broker=broker
        )

        steps.append(WorkflowStep(
            step_number=step_counter,
            action_type="PLACE_SAFETY_SL",
            target_role="STOPLOSS",
            target_quantity=new_remaining_qty,
            target_price=stoploss_price,
            cancel_order_id=None,
            cancel_broker_order_id=None,
            order_spec=replacement_sl_spec
        ))
        expected_next_state = "PARTIALLY_PROTECTED"
    else:
        steps.append(WorkflowStep(
            step_number=step_counter,
            action_type="CLOSE_TRADE",
            target_role=assigned_role,
            target_quantity=0,
            target_price=None,
            cancel_order_id=None,
            cancel_broker_order_id=None,
            order_spec=None
        ))
        expected_next_state = "CLOSED"

    return WorkflowPlan(
        trade_id=state.trade_id,
        trigger_event=event,
        current_position_state=state.position_state,
        expected_next_position_state=expected_next_state,
        steps=steps,
        remaining_quantity_after_workflow=new_remaining_qty,
        is_valid=True,
        rejection_reason=None
    )


def detect_tick_trigger_event(
    state: ReconstructedPositionState,
    current_ltp: Decimal,
    entry_action: str,
    entry_filled_qty: int,
    t1_price: Optional[Decimal],
    t2_price: Optional[Decimal],
    t3_price: Optional[Decimal]
) -> Tuple[Optional[str], int, Decimal]:
    """
    Pure side-effect-free helper function to evaluate live market LTP against target prices
    and determine the triggering event, target quantity, and exit target price.

    Delegates quantity split calculations strictly to child_order_builder.calculate_target_split_quantities.

    Args:
        state (ReconstructedPositionState): Current position state.
        current_ltp (Decimal): Live market Last Traded Price.
        entry_action (str): BUY or SELL.
        entry_filled_qty (int): Total filled entry quantity Q.
        t1_price (Optional[Decimal]): T1 price.
        t2_price (Optional[Decimal]): T2 price.
        t3_price (Optional[Decimal]): T3 price.

    Returns:
        Tuple[Optional[str], int, Decimal]: (trigger_event, target_quantity, exit_price)
    """
    from services.order_manager.child_order_builder import calculate_target_split_quantities

    current_ltp = Decimal(str(current_ltp))
    is_buy = (entry_action.upper() == "BUY")

    tp1_split, tp2_split, tp3_split = calculate_target_split_quantities(entry_filled_qty)

    # 1. TP1 Check
    if t1_price is not None and "TARGET_1" not in state.executed_targets:
        t1_price = Decimal(str(t1_price))
        if (is_buy and current_ltp >= t1_price) or (not is_buy and current_ltp <= t1_price):
            target_qty = min(state.remaining_quantity, tp1_split)
            return "TP1_HIT", target_qty, t1_price

    # 2. TP2 Check
    if t2_price is not None and "TARGET_2" not in state.executed_targets and "TARGET_1" in state.executed_targets:
        t2_price = Decimal(str(t2_price))
        if (is_buy and current_ltp >= t2_price) or (not is_buy and current_ltp <= t2_price):
            target_qty = min(state.remaining_quantity, tp2_split)
            return "TP2_HIT", target_qty, t2_price

    # 3. TP3 Check
    if t3_price is not None and "TARGET_3" not in state.executed_targets and "TARGET_2" in state.executed_targets:
        t3_price = Decimal(str(t3_price))
        if (is_buy and current_ltp >= t3_price) or (not is_buy and current_ltp <= t3_price):
            return "TP3_HIT", state.remaining_quantity, t3_price

    # 4. Initial SL Check
    if state.active_sl_price is not None:
        active_sl = Decimal(str(state.active_sl_price))
        if (is_buy and current_ltp <= active_sl) or (not is_buy and current_ltp >= active_sl):
            return "SL_HIT", state.remaining_quantity, active_sl

    return None, 0, Decimal("0")

