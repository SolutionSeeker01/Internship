# Backend/services/order_manager/order_manager_service.py
"""
Order Manager Core Service - Thin Workflow Orchestration Engine

Implements Section 5.15 of ARCHITECTURE_REFERENCE.md (v1.5.3).
Follows Principle P2 (Thin Coordinator Pattern) and Principle P10 (Client Execution Isolation).

Responsibilities:
  1. Receive broker order updates and live market tick events.
  2. Load trade and order records via database repositories.
  3. Delegate state evaluation to position_state_reconstructor.
  4. Delegate workflow planning to target_execution_workflow.
  5. Delegate trailing stop mathematics to trailing_stop_engine.
  6. Dispatch execution steps via BrokerInterface.
  7. Persist trade state updates via trade_repository and order_repository.
  8. Emit operational observation events for dashboards/WebSockets.

Must NOT contain internal business math, state rules, or payload construction logic.
"""

from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, List, Tuple

from database import trade_repository, order_repository
from models.trade import Trade
from models.order import Order
from services.order_manager.position_state_reconstructor import reconstruct_position_state, ReconstructedPositionState
from services.order_manager.target_execution_workflow import plan_target_execution_workflow, WorkflowPlan, WorkflowStep
from services.order_manager.trailing_stop_engine import (
    is_trailing_stop_activated,
    calculate_trailing_stop_price,
    should_emit_sl_modification,
    is_trailing_exit_triggered
)
from utils.logger import get_logger

logger = get_logger(__name__)


class OrderManagerService:
    """
    Thin coordinator orchestrating post-entry position lifecycle execution.
    """

    def __init__(self, broker_factory: Any, session_factory: Optional[Any] = None):
        """
        Args:
            broker_factory: Factory providing client-bound BrokerInterface adapters.
            session_factory: Optional SQLAlchemy session factory.
        """
        self.broker_factory = broker_factory
        self.session_factory = session_factory

    def process_market_tick(
        self,
        trade_id: int,
        current_ltp: Decimal,
        broker_account: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Processes a live market tick event for an active trade.

        Flow:
          1. Fetch trade record.
          2. Reconstruct position state via position_state_reconstructor.
          3. Evaluate Target Hits (TP1, TP2, TP3) or Initial SL Hit against LTP.
          4. Evaluate Trailing Stop activation and updates via trailing_stop_engine.
          5. If trigger condition met, generate WorkflowPlan via target_execution_workflow.
          6. Execute WorkflowPlan via BrokerInterface and update repositories.

        Returns:
            Dict[str, Any]: Result summary of the tick processing.
        """
        current_ltp = Decimal(str(current_ltp))
        db = self.session_factory() if self.session_factory else None

        try:
            trade = trade_repository.get_trade_by_id(trade_id, session=db)
            if not trade or trade.status == "CLOSED":
                return {"status": "SKIPPED", "reason": "Trade not found or already CLOSED"}

            # Fetch child orders
            entry_order = order_repository.get_entry_order_by_execution_target_id(trade.execution_target_id, session=db)
            if not entry_order:
                return {"status": "SKIPPED", "reason": "Entry order record missing"}

            child_orders = order_repository.get_child_orders_by_parent_id(entry_order.id, session=db)
            child_order_dicts = [
                {
                    "id": o.id,
                    "order_role": o.order_role,
                    "status": o.status,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "price": o.price,
                    "trigger_price": o.trigger_price,
                    "broker_order_id": o.broker_order_id
                }
                for o in child_orders
            ]

            # 1. Delegate Position State Reconstruction
            state = reconstruct_position_state(
                trade_id=trade.id,
                execution_target_id=trade.execution_target_id,
                entry_filled_qty=trade.entry_filled_qty or entry_order.filled_quantity or entry_order.quantity,
                trade_status=trade.status,
                trailing_sl_activated=trade.trailing_sl_activated,
                child_orders=child_order_dicts
            )

            if state.position_state == "CLOSED":
                return {"status": "SKIPPED", "reason": "Position state evaluates to CLOSED"}

            # Read Strategy Setup Prices
            entry_action = entry_order.action
            entry_price = Decimal(str(trade.entry_filled_price or trade.entry_intended_price))
            sl_price = Decimal(str(trade.sl_intended))
            t1_price = Decimal(str(trade.t1_intended)) if trade.t1_intended is not None else None
            t2_price = Decimal(str(trade.t2_intended)) if trade.t2_intended is not None else None
            t3_price = Decimal(str(trade.t3_intended)) if trade.t3_intended is not None else None

            # 2. Delegate Target Hit & Event Detection to Pure Module (Principle P1 & P2)
            from services.order_manager.target_execution_workflow import detect_tick_trigger_event

            entry_filled_qty = trade.entry_filled_qty or entry_order.filled_quantity or entry_order.quantity
            trigger_event, target_qty, target_price = detect_tick_trigger_event(
                state=state,
                current_ltp=current_ltp,
                entry_action=entry_action,
                entry_filled_qty=entry_filled_qty,
                t1_price=t1_price,
                t2_price=t2_price,
                t3_price=t3_price
            )

            # 3. Trailing Stop Engine Evaluation (If no TP/Initial SL hit)
            if not trigger_event and t1_price:
                # Delegate activation check (one-way latch)
                activated = is_trailing_stop_activated(
                    entry_action=entry_action,
                    entry_price=entry_price,
                    t1_price=t1_price,
                    current_ltp=current_ltp,
                    already_activated=trade.trailing_sl_activated
                )

                if activated and not trade.trailing_sl_activated:
                    trade_repository.update_trade(trade.id, trailing_sl_activated=True, session=db)
                    if db:
                        db.commit()

                if activated:
                    # Delegate theoretical trailing SL calculation
                    new_trailing_sl = calculate_trailing_stop_price(
                        entry_action=entry_action,
                        original_sl=sl_price,
                        entry_price=entry_price,
                        t1_price=t1_price,
                        current_ltp=current_ltp
                    )

                    # Check Trailing Exit Trigger
                    if is_trailing_exit_triggered(entry_action, state.active_sl_price or new_trailing_sl, current_ltp):
                        trigger_event = "TRAILING_SL_HIT"
                        target_qty = state.remaining_quantity
                        target_price = state.active_sl_price or new_trailing_sl
                    elif state.active_sl_price and should_emit_sl_modification(entry_action, state.active_sl_price, new_trailing_sl):
                        # Trailing SL update required -> modify active SL order at broker
                        broker_adapter = self.broker_factory.get_broker(entry_order.broker)
                        if state.active_sl_broker_order_id:
                            broker_adapter.modify_order(state.active_sl_broker_order_id, {"price": new_trailing_sl, "trigger_price": new_trailing_sl})
                            if state.active_sl_order_id:
                                order_repository.update_order(state.active_sl_order_id, price=new_trailing_sl, trigger_price=new_trailing_sl, session=db)
                            if db and self.session_factory:
                                db.commit()
                            return {"status": "SL_MODIFIED", "new_sl_price": float(new_trailing_sl)}

            # 4. If Trigger Event Occurred -> Generate and Execute WorkflowPlan
            if trigger_event:
                plan = plan_target_execution_workflow(
                    state=state,
                    trigger_event=trigger_event,
                    target_quantity=target_qty,
                    target_price=target_price,
                    parent_order_id=entry_order.id,
                    symbol=entry_order.symbol,
                    exchange=entry_order.exchange,
                    broker=entry_order.broker,
                    entry_action=entry_action,
                    stoploss_price=sl_price
                )

                if plan.is_valid:
                    res = self._execute_workflow_plan(plan, entry_order, broker_account, db=db)
                    return {"status": "EXECUTED", "trigger_event": trigger_event, "plan_result": res}
                else:
                    return {"status": "REJECTED", "reason": plan.rejection_reason}

            return {"status": "NO_CHANGE", "current_ltp": float(current_ltp)}

        finally:
            if db and self.session_factory:
                db.close()

    def _execute_workflow_plan(
        self,
        plan: WorkflowPlan,
        parent_order: Order,
        broker_account: Optional[Any] = None,
        db: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Dispatches the steps in a WorkflowPlan using BrokerInterface and repositories.
        """
        broker_adapter = self.broker_factory.get_broker(parent_order.broker)
        executed_steps = []

        for step in plan.steps:
            if step.action_type == "CANCEL_SL":
                if step.cancel_broker_order_id:
                    broker_adapter.cancel_order(step.cancel_broker_order_id)
                if step.cancel_order_id:
                    order_repository.update_order(step.cancel_order_id, status="CANCELLED", cancelled_at=datetime.now(), session=db)
                executed_steps.append("CANCEL_SL")

            elif step.action_type == "PLACE_TARGET_LIMIT" and step.order_spec:
                spec = step.order_spec
                confirmation = broker_adapter.place_order(spec, spec.idempotency_key)
                
                # Record target order in orders table
                child_order = order_repository.create_order(
                    idempotency_key=spec.idempotency_key,
                    symbol=spec.symbol,
                    exchange=spec.exchange,
                    action=spec.action,
                    order_type=spec.order_type,
                    quantity=spec.quantity,
                    broker=spec.broker,
                    order_role=spec.order_role,
                    parent_order_id=parent_order.id,
                    broker_order_id=confirmation.broker_order_id,
                    price=spec.price,
                    status="COMPLETE", # Simulated fill for target execution workflow
                    filled_quantity=spec.quantity,
                    average_price=spec.price,
                    placed_at=datetime.now(),
                    session=db
                )
                executed_steps.append(f"PLACE_TARGET_LIMIT_{spec.order_role}")

            elif step.action_type == "PLACE_SAFETY_SL" and step.order_spec:
                spec = step.order_spec
                confirmation = broker_adapter.place_order(spec, spec.idempotency_key)
                
                # Record replacement safety SL order in orders table
                order_repository.create_order(
                    idempotency_key=spec.idempotency_key,
                    symbol=spec.symbol,
                    exchange=spec.exchange,
                    action=spec.action,
                    order_type=spec.order_type,
                    quantity=spec.quantity,
                    broker=spec.broker,
                    order_role=spec.order_role,
                    parent_order_id=parent_order.id,
                    broker_order_id=confirmation.broker_order_id,
                    price=spec.price,
                    trigger_price=spec.trigger_price,
                    status="OPEN",
                    placed_at=datetime.now(),
                    session=db
                )
                
                # Update trade status
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=db)
                if trade:
                    trade_repository.update_trade(trade.id, status="PARTIALLY_CLOSED", session=db)
                executed_steps.append("PLACE_SAFETY_SL")

            elif step.action_type == "CLOSE_TRADE":
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=db)
                if trade:
                    trade_repository.update_trade(trade.id, status="CLOSED", closed_at=datetime.now(), session=db)
                executed_steps.append("CLOSE_TRADE")

        return {
            "expected_next_state": plan.expected_next_position_state,
            "executed_steps": executed_steps
        }


def math_floor(val: Decimal) -> int:
    import math
    return math.floor(float(val))
