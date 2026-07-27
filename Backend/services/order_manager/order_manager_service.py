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
                    status="PLACED",        # Updated to COMPLETE by broker order update callback on fill
                    filled_quantity=0,
                    average_price=None,
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

                from dev_tools.drm import global_event_bus, RuntimeEvent
                global_event_bus.publish(RuntimeEvent(
                    event_type="SAFETY_SL_PLACED",
                    component="ORDER_MGR",
                    trade_id=plan.trade_id,
                    order_id=confirmation.broker_order_id,
                    payload={"quantity": spec.quantity, "trigger_price": float(spec.trigger_price or 0), "limit_price": float(spec.price)}
                ))

            elif step.action_type == "CLOSE_TRADE":
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=db)
                if trade:
                    trade_repository.update_trade(trade.id, status="CLOSED", closed_at=datetime.now(), session=db)
                executed_steps.append("CLOSE_TRADE")

                from dev_tools.drm import global_event_bus, RuntimeEvent
                global_event_bus.publish(RuntimeEvent(
                    event_type="TRADE_COMPLETED",
                    component="ORDER_MGR",
                    trade_id=plan.trade_id,
                    payload={"status": "CLOSED"}
                ))

        return {
            "expected_next_state": plan.expected_next_position_state,
            "executed_steps": executed_steps
        }

    def process_broker_order_update(self, order_update: Dict[str, Any]) -> None:
        """
        Receives a normalized broker order update event and updates the corresponding
        order row in the database.

        Implements Section 5.15 Subsection 4 (Broker Order Update Handling).
        Called from the KiteTicker on_order_update callback wired during start_feed().

        State transitions applied per broker-reported status:
          COMPLETE / FILLED          → status='COMPLETE', fills filled_quantity + average_price
          CANCELLED / REJECTED       → status='CANCELLED' or 'REJECTED', no fill data
          OPEN / AMO REQ / PENDING   → status='OPEN' (re-confirm placement, no-op if already PLACED)

        Constraints:
          - NO business logic or position state evaluation
          - NO broker API calls
          - Performs only the DB update implied by the broker event
        """
        broker_order_id = str(order_update.get("order_id", ""))
        broker_status = str(order_update.get("status", "")).upper()
        filled_qty = int(order_update.get("filled_quantity", 0) or 0)
        avg_price = order_update.get("average_price") or order_update.get("price")

        if not broker_order_id:
            logger.warning("OrderManagerService.process_broker_order_update: received update with no order_id — skipping.")
            return

        # Map broker status string to platform status
        STATUS_MAP = {
            "COMPLETE": "COMPLETE",
            "FILLED": "COMPLETE",
            "CANCELLED": "CANCELLED",
            "REJECTED": "REJECTED",
            "OPEN": "OPEN",
            "AMO REQ": "PLACED",
            "PENDING": "PLACED",
            "TRIGGER PENDING": "PLACED",
        }
        platform_status = STATUS_MAP.get(broker_status)
        if platform_status is None:
            logger.debug(f"OrderManagerService.process_broker_order_update: unhandled broker status '{broker_status}' for order {broker_order_id} — skipping.")
            return

        db = self.session_factory() if self.session_factory else None
        own_session = db is not None
        if not own_session:
            from database.db import SessionLocal
            db = SessionLocal()
            own_session = True

        try:
            order = order_repository.get_order_by_broker_order_id(broker_order_id, session=db)
            if order is None:
                # This can happen for SL orders placed by OrderManagerService that aren't tracked
                # via the entry flow. Log at debug level — not an error.
                logger.debug(f"OrderManagerService.process_broker_order_update: no local order found for broker_order_id={broker_order_id} (status={broker_status}) — skipping.")
                return

            update_kwargs: Dict[str, Any] = {"status": platform_status}
            if platform_status == "COMPLETE":
                update_kwargs["filled_quantity"] = filled_qty
                if avg_price is not None:
                    update_kwargs["average_price"] = float(avg_price)

            order_repository.update_order(order.id, session=db, **update_kwargs)
            db.commit()

            logger.info(
                f"OrderManagerService: order ID {order.id} (broker_order_id={broker_order_id}) "
                f"updated to status='{platform_status}' (broker reported: '{broker_status}', "
                f"filled_qty={filled_qty})."
            )

            # ── INITIAL SAFETY STOP-LOSS PLACEMENT ────────────────────────────────────
            # Business Requirement: Immediately after the ENTRY order is confirmed FILLED,
            # a protective Stop-Loss order MUST be placed at the broker before runtime
            # tick monitoring begins.
            if platform_status == "COMPLETE" and getattr(order, "order_role", "") == "ENTRY":
                try:
                    logger.info(f"Entry order {order.id} (target {order.execution_target_id}) FILLED. Placing initial protective Safety Stop-Loss...")
                    trade = trade_repository.get_trade_by_execution_target_id(order.execution_target_id, session=db)
                    if trade and trade.status in ("OPEN", "PARTIALLY_CLOSED"):
                        # Check if a live STOPLOSS order already exists to prevent duplicates
                        existing_sl = order_repository.get_active_sl_order_by_parent_id(order.id, session=db)
                        if not existing_sl:
                            from services.order_manager.child_order_builder import build_child_order_specs
                            effective_filled_qty = filled_qty if filled_qty > 0 else order.quantity

                            specs = build_child_order_specs(
                                parent_order_id=order.id,
                                execution_target_id=order.execution_target_id,
                                filled_quantity=effective_filled_qty,
                                entry_action=order.action,
                                symbol=order.symbol,
                                exchange=order.exchange,
                                broker=order.broker,
                                stoploss_price=Decimal(str(trade.sl_intended)),
                                t1_price=Decimal(str(trade.t1_intended)) if trade.t1_intended else None,
                                t2_price=Decimal(str(trade.t2_intended)) if trade.t2_intended else None,
                                t3_price=Decimal(str(trade.t3_intended)) if trade.t3_intended else None
                            )

                            if specs.stop_loss:
                                sl_spec = specs.stop_loss
                                broker_adapter = self.broker_factory.get_broker(order.broker)
                                sl_confirmation = broker_adapter.place_order(sl_spec, sl_spec.idempotency_key)

                                order_repository.create_order(
                                    idempotency_key=sl_spec.idempotency_key,
                                    symbol=sl_spec.symbol,
                                    exchange=sl_spec.exchange,
                                    action=sl_spec.action,
                                    order_type=sl_spec.order_type,
                                    quantity=sl_spec.quantity,
                                    broker=sl_spec.broker,
                                    order_role="STOPLOSS",
                                    parent_order_id=order.id,
                                    broker_order_id=sl_confirmation.broker_order_id,
                                    price=sl_spec.price,
                                    trigger_price=sl_spec.trigger_price,
                                    status="OPEN",
                                    placed_at=datetime.now(),
                                    session=db
                                )
                                db.commit()
                                logger.info(
                                    f"Initial protective Safety Stop-Loss placed successfully: "
                                    f"broker_order_id={sl_confirmation.broker_order_id}, qty={sl_spec.quantity}, "
                                    f"price={sl_spec.price} for trade {trade.id}."
                                )
                except Exception as sl_err:
                    logger.error(f"Failed to place initial protective Safety Stop-Loss for entry order {order.id}: {sl_err}", exc_info=True)

            from dev_tools.drm import global_event_bus, RuntimeEvent
            global_event_bus.publish(RuntimeEvent(
                event_type="BROKER_ORDER_UPDATE",
                component="ORDER_MGR",
                trade_id=getattr(order, "execution_target_id", 0),
                order_id=broker_order_id,
                payload={"platform_status": platform_status, "broker_status": broker_status, "filled_qty": filled_qty}
            ))

        except Exception as e:
            if own_session:
                db.rollback()
            logger.error(f"OrderManagerService.process_broker_order_update failed for broker_order_id={broker_order_id}: {e}", exc_info=True)
        finally:
            if own_session:
                db.close()


def math_floor(val: Decimal) -> int:
    import math
    return math.floor(float(val))
