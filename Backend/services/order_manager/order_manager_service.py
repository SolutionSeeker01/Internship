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
from services.order_manager.position_state_reconstructor import reconstruct_position_state, ReconstructedPositionState, get_protection_mode

from services.order_manager.target_execution_workflow import plan_target_execution_workflow, WorkflowPlan, WorkflowStep
from services.order_manager.trailing_stop_engine import (
    is_trailing_stop_activated,
    calculate_trailing_stop_price,
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
        import threading
        self.broker_factory = broker_factory
        self.session_factory = session_factory
        self._trade_locks: Dict[int, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_trade_lock(self, trade_id: int):
        with self._global_lock:
            if trade_id not in self._trade_locks:
                import threading
                self._trade_locks[trade_id] = threading.Lock()
            return self._trade_locks[trade_id]

    def process_market_tick(
        self,
        trade_id: int,
        current_ltp: Decimal,
        broker_account: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Processes a live market tick event for an active trade.
        """
        trade_lock = self._get_trade_lock(trade_id)
        if not trade_lock.acquire(blocking=False):
            logger.debug(f"Tick skipped for Trade ID {trade_id}: Lock already held by another tick worker.")
            return {"status": "SKIPPED", "reason": "TRADE_LOCKED"}

        try:
            return self._process_market_tick_internal(trade_id, current_ltp, broker_account)
        finally:
            trade_lock.release()

    def _process_market_tick_internal(
        self,
        trade_id: int,
        current_ltp: Decimal,
        broker_account: Optional[Any] = None
    ) -> Dict[str, Any]:
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

            # Duplicate Cancellation Guard (Invariant 5): If cancellation is in-flight, suppress duplicate cancel requests
            if state.position_state == "SL_CANCEL_PENDING" or getattr(trade, "position_state", "") == "SL_CANCEL_PENDING":
                logger.info(f"Trade ID {trade.id} is in SL_CANCEL_PENDING. Suppressing duplicate broker cancellation.")
                return {"status": "SL_CANCEL_PENDING", "position_state": "SL_CANCEL_PENDING", "reason": "Cancellation workflow in progress"}


            # Duplicate Exit Protection: If exit order is in-flight, suppress duplicate exit attempts
            if state.position_state == "EXIT_PENDING" or getattr(trade, "position_state", "") == "EXIT_PENDING":
                logger.info(f"Trade ID {trade.id} is in EXIT_PENDING. Suppressing duplicate software exit order.")
                return {"status": "EXIT_PENDING", "position_state": "EXIT_PENDING", "reason": "Software exit order already in-flight"}

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

            # 3. Trailing Stop Engine Evaluation (Phase 2, 3 & 4 Integration)
            if not trigger_event and t1_price:
                # Delegate 70% activation check (one-way latch)
                activated = is_trailing_stop_activated(
                    entry_action=entry_action,
                    entry_price=entry_price,
                    t1_price=t1_price,
                    current_ltp=current_ltp,
                    already_activated=trade.trailing_sl_activated
                )

                # PHASE 2 HANDOVER: Transition from BROKER_PROTECTED -> SL_CANCEL_PENDING -> SOFTWARE_TRAILING_ACTIVE
                if activated and not trade.trailing_sl_activated:
                    logger.info(f"Phase 2 Handover Triggered for Trade ID {trade.id}: 70% to TP1 reached at LTP {current_ltp}.")
                    
                    # Step 1: Transition state to SL_CANCEL_PENDING
                    trade_repository.update_trade(trade.id, position_state="SL_CANCEL_PENDING", session=db)
                    if db:
                        db.commit()

                    # Step 2: Issue broker SL cancellation
                    broker_cancel_confirmed = False
                    sl_filled_at_broker = False

                    if state.active_sl_broker_order_id:
                        broker_adapter = self.broker_factory.get_broker(entry_order.broker)
                        try:
                            cancel_response = broker_adapter.cancel_order(state.active_sl_broker_order_id)
                            cancel_status = str(cancel_response.get("status", "")).upper()
                            
                            if cancel_status in ("CANCELLED", "SUCCESS"):
                                broker_cancel_confirmed = True
                            elif cancel_status in ("FILLED", "COMPLETE"):
                                sl_filled_at_broker = True
                            else:
                                logger.info(f"Broker cancel returned status '{cancel_status}'. Handover remaining SL_CANCEL_PENDING.")
                        except Exception as cancel_err:
                            err_msg = str(cancel_err).lower()
                            if "already cancelled" in err_msg:
                                broker_cancel_confirmed = True
                            elif "already executed" in err_msg or "filled" in err_msg:
                                sl_filled_at_broker = True
                            else:
                                logger.warning(f"Broker SL cancel attempt failed for Trade ID {trade.id}: {cancel_err}")

                    # Step 3: Handle Broker Outcomes
                    if sl_filled_at_broker:
                        trade_repository.update_trade(trade.id, status="CLOSED", position_state="CLOSED", closed_at=datetime.now(), session=db)
                        if db and self.session_factory:
                            db.commit()
                        from services.runtime.runtime_coordinator import get_runtime_coordinator
                        coordinator = get_runtime_coordinator()
                        if coordinator and coordinator._is_initialized:
                            coordinator.close_and_unregister_trade(trade.id)
                        logger.info(f"Handover aborted for Trade ID {trade.id}: Initial SL executed at broker.")
                        return {"status": "SL_FILLED_AT_BROKER", "position_state": "CLOSED"}

                    if broker_cancel_confirmed or not state.active_sl_broker_order_id:
                        initial_trailing_sl = calculate_trailing_stop_price(
                            entry_action=entry_action,
                            original_sl=sl_price,
                            entry_price=entry_price,
                            t1_price=t1_price,
                            current_ltp=current_ltp
                        )

                        trade_repository.update_trade(
                            trade.id,
                            position_state="SOFTWARE_TRAILING_ACTIVE",
                            active_trailing_sl=initial_trailing_sl,
                            trailing_sl_activated=True,
                            session=db
                        )
                        if state.active_sl_order_id:
                            order_repository.update_order(state.active_sl_order_id, status="CANCELLED", session=db)
                        
                        if db and self.session_factory:
                            db.commit()

                        from services.order_manager.position_state_reconstructor import validate_position_invariants
                        violations = validate_position_invariants(
                            position_state="SOFTWARE_TRAILING_ACTIVE",
                            active_trailing_sl=initial_trailing_sl,
                            active_sl_broker_order_id=None
                        )
                        assert len(violations) == 0, f"Invariant Violation during Handover: {violations}"

                        logger.info(f"Handover SUCCESS for Trade ID {trade.id}: SOFTWARE_TRAILING_ACTIVE at SL {initial_trailing_sl}.")
                        return {
                            "status": "HANDOVER_COMPLETE",
                            "position_state": "SOFTWARE_TRAILING_ACTIVE",
                            "active_trailing_sl": float(initial_trailing_sl)
                        }

                    return {"status": "SL_CANCEL_PENDING", "position_state": "SL_CANCEL_PENDING"}

                # PHASE 3 & PHASE 4: SOFTWARE TRAILING ENGINE & EXIT EXECUTION
                current_mode = get_protection_mode(state.position_state)
                if trade.trailing_sl_activated and current_mode == "SOFTWARE":
                    active_sl = Decimal(str(trade.active_trailing_sl or sl_price))

                    # PHASE 4: BREACH DETECTION & EXIT EXECUTION
                    from services.order_manager.trailing_stop_engine import is_trailing_exit_triggered
                    if is_trailing_exit_triggered(entry_action, active_sl, current_ltp):
                        logger.info(f"Phase 4 Software SL Breach Triggered for Trade ID {trade.id} at LTP {current_ltp} vs SL {active_sl}.")

                        # Step 1: Immediate State Transition to EXIT_PENDING (Duplicate Exit Protection)
                        trade_repository.update_trade(trade.id, position_state="EXIT_PENDING", session=db)
                        if db:
                            db.commit()

                        # Step 2: Exit Order Placement (5% Execution Buffer)
                        is_buy = (entry_action.upper() == "BUY")
                        buffer_pct = Decimal("0.05")
                        limit_exit_price = active_sl * (Decimal("1") - buffer_pct) if is_buy else active_sl * (Decimal("1") + buffer_pct)

                        plan = plan_target_execution_workflow(
                            state=state,
                            trigger_event="TRAILING_SL_HIT",
                            target_quantity=state.remaining_quantity,
                            target_price=active_sl,
                            parent_order_id=entry_order.id,
                            symbol=entry_order.symbol,
                            exchange=entry_order.exchange,
                            broker=entry_order.broker,
                            entry_action=entry_action,
                            stoploss_price=active_sl
                        )


                        broker_adapter = self.broker_factory.get_broker(entry_order.broker)
                        exit_step = [s for s in plan.steps if s.action_type == "PLACE_TARGET_LIMIT"][0]
                        exit_spec = exit_step.order_spec

                        try:
                            # Pre-persist software exit order into orders table (H6)
                            sw_order = order_repository.create_order(
                                idempotency_key=exit_spec.idempotency_key,
                                symbol=exit_spec.symbol,
                                exchange=exit_spec.exchange,
                                action=exit_spec.action,
                                order_type=exit_spec.order_type,
                                quantity=exit_spec.quantity,
                                broker=exit_spec.broker,
                                order_role="EXIT_ALL",
                                parent_order_id=entry_order.id,
                                price=exit_spec.price,
                                status="PLACED",
                                placed_at=datetime.now(),
                                session=db
                            )
                            if db:
                                db.commit()

                            exit_res = broker_adapter.place_order(exit_spec.to_dict(), exit_spec.idempotency_key)
                            confirm_broker_id = exit_res.get("broker_order_id") if isinstance(exit_res, dict) else getattr(exit_res, "broker_order_id", None)
                            order_status = str(exit_res.get("status", "")).upper()

                            if confirm_broker_id and sw_order:
                                order_repository.update_order(sw_order.id, broker_order_id=confirm_broker_id, session=db)
                                if db:
                                    db.commit()

                            if order_status in ("COMPLETE", "FILLED", "SUCCESS"):
                                if sw_order:
                                    order_repository.update_order(sw_order.id, status="COMPLETE", filled_quantity=exit_spec.quantity, average_price=float(limit_exit_price), session=db)
                                trade_repository.update_trade(trade.id, status="CLOSED", position_state="CLOSED", closed_at=datetime.now(), session=db)
                                if db and self.session_factory:
                                    db.commit()
                                from services.runtime.runtime_coordinator import get_runtime_coordinator
                                coordinator = get_runtime_coordinator()
                                if coordinator and coordinator._is_initialized:
                                    coordinator.close_and_unregister_trade(trade.id)
                                return {"status": "SOFTWARE_SL_HIT", "position_state": "CLOSED", "exit_price": float(limit_exit_price)}
                            elif order_status == "REJECTED":
                                if sw_order:
                                    order_repository.update_order(sw_order.id, status="REJECTED", session=db)
                                trade_repository.update_trade(trade.id, position_state="SOFTWARE_TRAILING_ACTIVE", session=db)
                                if db and self.session_factory:
                                    db.commit()
                                return {"status": "EXIT_ORDER_REJECTED", "position_state": "SOFTWARE_TRAILING_ACTIVE"}
                            else:
                                return {"status": "EXIT_ORDER_PLACED", "position_state": "EXIT_PENDING"}
                        except Exception as exit_err:
                            logger.error(f"Software exit submission failed for Trade ID {trade.id}: {exit_err}")
                            trade_repository.update_trade(trade.id, position_state="SOFTWARE_TRAILING_ACTIVE", session=db)
                            if db and self.session_factory:
                                db.commit()
                            return {"status": "EXIT_ORDER_REJECTED", "position_state": "SOFTWARE_TRAILING_ACTIVE"}

                    # PHASE 3: Continuous Monotonic Ratchet & DB Persistence
                    candidate_sl = calculate_trailing_stop_price(
                        entry_action=entry_action,
                        original_sl=sl_price,
                        entry_price=entry_price,
                        t1_price=t1_price,
                        current_ltp=current_ltp
                    )

                    from services.order_manager.trailing_stop_engine import update_monotonic_trailing_sl
                    ratcheted_sl = update_monotonic_trailing_sl(
                        entry_action=entry_action,
                        active_trailing_sl=trade.active_trailing_sl,
                        new_calculated_sl=candidate_sl
                    )

                    current_active_sl = trade.active_trailing_sl
                    sl_improved = False

                    if current_active_sl is None:
                        sl_improved = True
                    elif entry_action.upper() == "BUY" and ratcheted_sl > current_active_sl:
                        sl_improved = True
                    elif entry_action.upper() == "SELL" and ratcheted_sl < current_active_sl:
                        sl_improved = True

                    if sl_improved:
                        trade_repository.update_trade(trade.id, active_trailing_sl=ratcheted_sl, session=db)
                        if db and self.session_factory:
                            db.commit()

                        from services.order_manager.position_state_reconstructor import validate_position_invariants
                        violations = validate_position_invariants(
                            position_state=state.position_state,
                            active_trailing_sl=ratcheted_sl,
                            active_sl_broker_order_id=None
                        )
                        assert len(violations) == 0, f"Invariant Violation in Phase 3 Engine: {violations}"

                        logger.info(f"Phase 3 Trailing Ratchet UPDATED Trade ID {trade.id}: active_trailing_sl={ratcheted_sl}.")
                        return {
                            "status": "SOFTWARE_TRAILING_UPDATED",
                            "active_trailing_sl": float(ratcheted_sl)
                        }
                    else:
                        return {
                            "status": "SOFTWARE_TRAILING_UNCHANGED",
                            "active_trailing_sl": float(current_active_sl)
                        }





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
                # Bug Fix (Production Validation): place_order() returns a dict; access safely.
                confirm_broker_id = confirmation.get("broker_order_id") if isinstance(confirmation, dict) else getattr(confirmation, "broker_order_id", None)

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
                    broker_order_id=confirm_broker_id,
                    price=spec.price,
                    status="PLACED",        # Updated to COMPLETE by broker order update callback on fill
                    filled_quantity=0,
                    average_price=None,
                    placed_at=datetime.now(),
                    session=db
                )
                executed_steps.append(f"PLACE_TARGET_LIMIT_{spec.order_role}")

                # Update trade status to PARTIALLY_CLOSED for target exits
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=db)
                if trade and "TARGET" in spec.order_role:
                    trade_repository.update_trade(trade.id, status="PARTIALLY_CLOSED", session=db)


            elif step.action_type == "PLACE_SAFETY_SL" and step.order_spec:
                spec = step.order_spec
                confirmation = broker_adapter.place_order(spec, spec.idempotency_key)
                # Bug Fix (Production Validation): place_order() returns a dict; access safely.
                confirm_broker_id = confirmation.get("broker_order_id") if isinstance(confirmation, dict) else getattr(confirmation, "broker_order_id", None)

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
                    broker_order_id=confirm_broker_id,
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
                    order_id=confirm_broker_id,
                    payload={"quantity": spec.quantity, "trigger_price": float(spec.trigger_price or 0), "limit_price": float(spec.price)}
                ))

            elif step.action_type == "CLOSE_TRADE":
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=db)
                if trade:
                    trade_repository.update_trade(trade.id, status="CLOSED", closed_at=datetime.now(), session=db)
                    from services.runtime.runtime_coordinator import get_runtime_coordinator
                    coordinator = get_runtime_coordinator()
                    if coordinator and coordinator._is_initialized:
                        coordinator.close_and_unregister_trade(trade.id)
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
                                # Bug Fix (Production Validation): place_order() returns a dict; access safely.
                                sl_broker_order_id = sl_confirmation.get("broker_order_id") if isinstance(sl_confirmation, dict) else getattr(sl_confirmation, "broker_order_id", None)

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
                                    broker_order_id=sl_broker_order_id,
                                    price=sl_spec.price,
                                    trigger_price=sl_spec.trigger_price,
                                    status="OPEN",
                                    placed_at=datetime.now(),
                                    session=db
                                )
                                db.commit()
                                logger.info(
                                    f"Initial protective Safety Stop-Loss placed successfully: "
                                    f"broker_order_id={sl_broker_order_id}, qty={sl_spec.quantity}, "
                                    f"price={sl_spec.price} for trade {trade.id}."
                                )
                except Exception as sl_err:
                    logger.error(f"Failed to place initial protective Safety Stop-Loss for entry order {order.id}: {sl_err}", exc_info=True)

            # If an exit order completes, update trade status to CLOSED and clean up runtime
            if platform_status == "COMPLETE" and getattr(order, "order_role", "") in ("STOPLOSS", "EXIT_ALL", "TARGET_3"):
                try:
                    trade = trade_repository.get_trade_by_execution_target_id(order.execution_target_id, session=db)
                    if trade and trade.status != "CLOSED":
                        trade_repository.update_trade(trade.id, status="CLOSED", position_state="CLOSED", closed_at=datetime.now(), session=db)
                        db.commit()
                        from services.runtime.runtime_coordinator import get_runtime_coordinator
                        coordinator = get_runtime_coordinator()
                        if coordinator and coordinator._is_initialized:
                            coordinator.close_and_unregister_trade(trade.id)
                except Exception as exit_close_err:
                    logger.error(f"Error closing/unregistering trade on exit order fill: {exit_close_err}", exc_info=True)

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
