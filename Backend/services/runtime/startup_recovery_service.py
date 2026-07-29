# Backend/services/runtime/startup_recovery_service.py
"""
Startup Recovery Service - Runtime Application Startup Recovery Orchestrator

Implements Stage 7A Step 2 of phase7_runtime_integration_plan.md and respects
Section 5.14 (Execution Target Recovery) and Section 12 (Crash Recovery) of
ARCHITECTURE_REFERENCE.md (v1.5.3).

Responsibilities:
  1. Part A: Recover orphaned EXECUTING targets via crash_recovery_scanner decision tree.
  2. Part B: Load active trade records ('OPEN', 'PARTIALLY_CLOSED') & child orders via repositories.
  3. Part C: Invoke position_state_reconstructor to rebuild in-memory position state DTOs.
  4. Part D: Request OrderManagerService creation via manager_factory and register with OrderManagerRegistry.
  5. Part E: Trigger symbol subscription callbacks for recovered active trade symbols.

Constraints:
  - NO business logic or trading calculations.
  - NO state machine rule re-implementations (uses crash_recovery_scanner & position_state_reconstructor).
  - Infrastructure recovery orchestrator only.
"""

from typing import List, Dict, Any, Optional, Callable
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database import trade_repository, order_repository
from services.crash_recovery_scanner import find_orphaned_executing_targets, reconcile_target
from services.order_manager.position_state_reconstructor import reconstruct_position_state, ReconstructedPositionState
from services.order_manager.order_manager_service import OrderManagerService
from services.runtime.order_manager_registry import OrderManagerRegistry
from utils.logger import get_logger

logger = get_logger(__name__)


class RecoveryException(Exception):
    """Base exception for startup recovery failures."""
    pass


class TargetRecoveryException(RecoveryException):
    """Raised when an orphaned execution target recovery attempt fails unexpectedly."""
    pass


class TradeReconstructionException(RecoveryException):
    """Raised when active trade position state reconstruction fails."""
    pass


class StartupRecoveryService:
    """
    Orchestrates application startup crash recovery for both orphaned entry execution targets
    and live active trade positions.
    """

    def __init__(
        self,
        registry: OrderManagerRegistry,
        manager_factory: Callable[[], Any],
        subscription_callback: Optional[Callable[[str], None]] = None,
        feed_manager: Optional[Any] = None
    ):
        """
        Args:
            registry (OrderManagerRegistry): The active in-memory trade manager registry.
            manager_factory (Callable[[], Any]): Required injected factory/callback responsible for
                creating initialized OrderManagerService instances.
            subscription_callback (Optional[Callable[[str], None]]): Optional legacy callback function.
            feed_manager (Optional[Any]): Optional AccountFeedManager instance for Phase 3 client market data feed recovery.
        """
        if registry is None:
            raise ValueError("registry is required for StartupRecoveryService.")
        if manager_factory is None:
            raise ValueError("manager_factory is required for StartupRecoveryService.")

        self.registry = registry
        self.manager_factory = manager_factory
        self.subscription_callback = subscription_callback
        self.feed_manager = feed_manager

    def execute_startup_recovery(
        self,
        timeout_seconds: int = 30,
        session: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Executes complete application startup recovery sequence.

        Flow:
          1. Recover orphaned EXECUTING targets (Section 5.14).
          2. Reconstruct & register active open trades (Section 12).
          3. Phase 3: Group active trades by broker_account_id, compute reference counts,
             create/reuse feeds, connect feeds, and batch-subscribe required symbols.

        Args:
            timeout_seconds (int): Timeout threshold in seconds for orphaned target scanner.
            session (Optional[Session]): Optional DB session.

        Returns:
            Dict[str, Any]: Diagnostic recovery summary report containing counts and metrics.
        """
        logger.info("Initiating Startup Recovery Service pipeline...")
        from dev_tools.drm import global_event_bus, RuntimeEvent
        global_event_bus.publish(RuntimeEvent(
            event_type="RECOVERY_STARTED",
            component="STARTUP_RECOVERY"
        ))

        db = session if session else SessionLocal()
        own_session = session is None

        target_results = {"recovered_submitted": 0, "reset_ready": 0, "failed": 0, "errors": 0}
        trade_results = {"reconstructed_trades": 0, "failed_trades": 0, "subscribed_symbols": set()}
        feed_results = {"recovered_broker_accounts": 0, "failed_broker_accounts": 0, "batched_subscriptions": {}}

        try:
            # -------------------------------------------------------------------
            # PART A: Orphaned Execution Target Recovery (Section 5.14)
            # -------------------------------------------------------------------
            orphaned_targets = find_orphaned_executing_targets(timeout_seconds=timeout_seconds, session=db)
            logger.info(f"Startup Recovery: Found {len(orphaned_targets)} orphaned EXECUTING target(s).")

            for target in orphaned_targets:
                target_id = target.get("id")
                try:
                    outcome = reconcile_target(target)
                    if outcome == "RECONCILED_SUBMITTED":
                        target_results["recovered_submitted"] += 1
                    elif outcome in ("RESET_TO_READY", "READY"):
                        target_results["reset_ready"] += 1
                    else:
                        target_results["failed"] += 1
                    logger.info(f"Target ID {target_id} recovery completed with outcome: {outcome}")
                except Exception as target_err:
                    target_results["errors"] += 1
                    logger.error(f"Failed to recover orphaned target ID {target_id}: {target_err}", exc_info=True)

            # -------------------------------------------------------------------
            # PART B & C: Active Trade Reconstruction & Registry Registration (Section 12)
            # -------------------------------------------------------------------
            open_trades = trade_repository.get_open_trades(session=db)
            logger.info(f"Startup Recovery: Found {len(open_trades)} active trade(s) ('OPEN'/'PARTIALLY_CLOSED').")

            # Intermediate grouping structure for Phase 3: broker_account_id -> {symbol: ref_count}
            broker_account_symbols: Dict[int, Dict[str, int]] = {}

            for trade in open_trades:
                trade_id = trade.id
                try:
                    restored_info = self._recover_single_active_trade(trade, session=db, subscribed_symbols=trade_results["subscribed_symbols"])
                    if restored_info:
                        trade_results["reconstructed_trades"] += 1
                        
                        # Extract broker_account_id and symbol for Phase 3 batched feed recovery
                        b_acc_id = restored_info.get("broker_account_id")
                        sym = restored_info.get("symbol")
                        if b_acc_id and sym:
                            if b_acc_id not in broker_account_symbols:
                                broker_account_symbols[b_acc_id] = {}
                            broker_account_symbols[b_acc_id][sym] = broker_account_symbols[b_acc_id].get(sym, 0) + 1
                except Exception as trade_err:
                    trade_results["failed_trades"] += 1
                    logger.error(f"Failed to recover active Trade ID {trade_id}: {trade_err}", exc_info=True)

            # -------------------------------------------------------------------
            # PART D: Phase 3 Client Feed Restoration & Batched Subscription
            # -------------------------------------------------------------------
            if self.feed_manager and broker_account_symbols:
                logger.info(f"Startup Recovery (Phase 3): Recovering feeds for {len(broker_account_symbols)} broker account(s)...")
                for b_acc_id, symbol_counts in broker_account_symbols.items():
                    try:
                        logger.info(f"Startup Recovery: Restoring Feed for broker_account_id {b_acc_id} with symbol counts: {symbol_counts}")
                        feed = self.feed_manager.get_or_create_feed(broker_account_id=b_acc_id)
                        
                        # Connect feed if not connected
                        if not feed.is_connected():
                            feed.connect()

                        # Batch subscribe symbols with computed reference counts
                        subscribed_batch = []
                        for sym, count in symbol_counts.items():
                            for _ in range(count):
                                feed.subscribe_symbol(sym)
                            subscribed_batch.append(sym)

                        feed_results["recovered_broker_accounts"] += 1
                        feed_results["batched_subscriptions"][b_acc_id] = subscribed_batch
                        logger.info(f"Startup Recovery: Successfully batch-subscribed {len(subscribed_batch)} symbol(s) on broker_account_id {b_acc_id}.")
                    except Exception as feed_err:
                        feed_results["failed_broker_accounts"] += 1
                        logger.error(f"Startup Recovery: Failed to recover feed for broker_account_id {b_acc_id}: {feed_err}", exc_info=True)

            summary = {
                "status": "COMPLETED",
                "orphaned_targets_found": len(orphaned_targets),
                "target_outcomes": target_results,
                "active_trades_found": len(open_trades),
                "reconstructed_trades": trade_results["reconstructed_trades"],
                "failed_trades": trade_results["failed_trades"],
                "subscribed_symbols": list(trade_results["subscribed_symbols"]),
                "feed_recovery": feed_results
            }
            logger.info(f"Startup Recovery Service pipeline finished cleanly. Summary: {summary}")

            global_event_bus.publish(RuntimeEvent(
                event_type="RECOVERY_COMPLETED",
                component="STARTUP_RECOVERY",
                payload=summary
            ))
            return summary

        finally:
            if own_session:
                db.close()

    def _recover_single_active_trade(
        self,
        trade: Any,
        session: Session,
        subscribed_symbols: set
    ) -> None:
        """
        Reconstructs and restores a single active trade instance into the runtime registry.
        """
        trade_id = trade.id
        execution_target_id = trade.execution_target_id

        # 1. Fetch parent entry order and child orders
        entry_order = order_repository.get_entry_order_by_execution_target_id(execution_target_id, session=session)
        if not entry_order:
            raise TradeReconstructionException(
                f"Trade ID {trade_id}: Missing entry order record for execution_target_id {execution_target_id}."
            )

        child_orders = order_repository.get_child_orders_by_parent_id(entry_order.id, session=session)
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

        entry_filled_qty = trade.entry_filled_qty or entry_order.filled_quantity or entry_order.quantity

        # 2. Invoke position_state_reconstructor
        state: ReconstructedPositionState = reconstruct_position_state(
            trade_id=trade_id,
            execution_target_id=execution_target_id,
            entry_filled_qty=entry_filled_qty,
            trade_status=trade.status,
            trailing_sl_activated=trade.trailing_sl_activated,
            child_orders=child_order_dicts
        )

        # Phase 6 Requirement: Reconcile In-Flight Pending Position States (SL_CANCEL_PENDING, TARGET_ORDER_PENDING, EXIT_PENDING)
        reconciled_state_str = self._reconcile_in_flight_trade_state(trade, entry_order, child_orders, state, session=session)

        if reconciled_state_str == "CLOSED" or state.position_state == "CLOSED":
            logger.warning(f"Trade ID {trade_id} evaluates to CLOSED during reconstruction. Skipping registry registration.")
            return False

        # Validate Invariants after recovery
        from services.order_manager.position_state_reconstructor import validate_position_invariants
        violations = validate_position_invariants(
            position_state=reconciled_state_str or state.position_state,
            active_trailing_sl=trade.active_trailing_sl,
            active_sl_broker_order_id=None if (reconciled_state_str or state.position_state) == "SOFTWARE_TRAILING_ACTIVE" else state.active_sl_broker_order_id
        )
        if len(violations) > 0:
            logger.warning(f"Phase 6 Recovery Invariant Violation warning for Trade ID {trade_id}: {violations}")

        # 3. Instantiate OrderManagerService via injected manager_factory
        manager_instance = self.manager_factory()

        # 4. Resolve BrokerAccount ID via client_id for Phase 3 feed recovery & scoped registry
        from models.broker_account import BrokerAccount
        from models.execution_target import ExecutionTarget
        broker_account_id = None
        
        client_id = getattr(entry_order, "client_id", None)
        if not client_id:
            try:
                target = session.query(ExecutionTarget).filter(ExecutionTarget.id == trade.execution_target_id).first()
                if target:
                    client_id = target.client_id
            except Exception:
                client_id = None

        if client_id:
            try:
                acc = session.query(BrokerAccount).filter(BrokerAccount.user_id == client_id).first()
                if acc:
                    broker_account_id = acc.id
            except Exception as b_err:
                logger.warning(f"Failed to resolve BrokerAccount for client_id {client_id} on Trade ID {trade_id}: {b_err}")

        # 5. Register in OrderManagerRegistry (scoped by broker_account_id and symbol)
        symbol = entry_order.symbol
        
        self.registry.register_trade(
            trade_id=trade_id,
            symbol=symbol,
            manager_instance=manager_instance,
            broker_account_id=broker_account_id
        )

        # 6. Trigger symbol subscription callback
        symbol_upper = symbol.strip().upper()
        subscribed_symbols.add(symbol_upper)

        if self.subscription_callback:
            try:
                self.subscription_callback(symbol_upper)
            except Exception as sub_err:
                logger.error(f"Subscription callback failed for symbol '{symbol_upper}' on Trade ID {trade_id}: {sub_err}")

        logger.info(
            f"Restored Trade ID {trade_id} into registry (State: '{reconciled_state_str or state.position_state}', "
            f"Symbol: '{symbol_upper}', Broker Account ID: {broker_account_id}, Trailing Activated: {trade.trailing_sl_activated})."
        )
        return {
            "trade_id": trade_id,
            "symbol": symbol_upper,
            "broker_account_id": broker_account_id
        }


    def _reconcile_in_flight_trade_state(
        self,
        trade: Any,
        entry_order: Any,
        child_orders: List[Any],
        state: ReconstructedPositionState,
        session: Session
    ) -> Optional[str]:
        """
        Phase 6 Recovery Decision Matrix for In-Flight Pending Position States:
          - SL_CANCEL_PENDING: Reconcile broker cancellation status.
          - TARGET_ORDER_PENDING: Reconcile target exit order status.
          - EXIT_PENDING: Reconcile software exit order status.
          - SOFTWARE_TRAILING_ACTIVE: Restore active_trailing_sl.
        """
        current_state = getattr(trade, "position_state", "") or state.position_state

        # 1. Recover SL_CANCEL_PENDING State
        if current_state == "SL_CANCEL_PENDING":
            logger.info(f"Phase 6 Recovery: Reconciling SL_CANCEL_PENDING for Trade ID {trade.id}...")
            sl_broker_id = state.active_sl_broker_order_id
            if sl_broker_id:
                try:
                    manager = self.manager_factory()
                    broker_adapter = manager.broker_factory.get_broker(entry_order.broker)
                    order_info = broker_adapter.get_order_history(sl_broker_id)
                    broker_status = str(order_info.get("status", "")).upper() if isinstance(order_info, dict) else "UNKNOWN"

                    if broker_status in ("CANCELLED", "REJECTED"):
                        init_sl = trade.active_trailing_sl or trade.sl_intended
                        trade_repository.update_trade(
                            trade.id,
                            position_state="SOFTWARE_TRAILING_ACTIVE",
                            active_trailing_sl=init_sl,
                            trailing_sl_activated=True,
                            session=session
                        )
                        if state.active_sl_order_id:
                            order_repository.update_order(state.active_sl_order_id, status="CANCELLED", session=session)
                        for o in child_orders:
                            o_b_id = getattr(o, "broker_order_id", o.get("broker_order_id") if isinstance(o, dict) else None)
                            if o_b_id == sl_broker_id:
                                o_id = getattr(o, "id", o.get("id") if isinstance(o, dict) else None)
                                if o_id:
                                    order_repository.update_order(o_id, status="CANCELLED", session=session)
                                    if isinstance(o, dict):
                                        o["status"] = "CANCELLED"
                                    else:
                                        o.status = "CANCELLED"

                        if session:
                            session.commit()
                        logger.info(f"Phase 6 Recovery: SL_CANCEL_PENDING reconciled -> SOFTWARE_TRAILING_ACTIVE (SL={init_sl}).")
                        return "SOFTWARE_TRAILING_ACTIVE"

                    elif broker_status in ("FILLED", "COMPLETE"):
                        trade_repository.update_trade(trade.id, status="CLOSED", position_state="CLOSED", session=session)
                        if session:
                            session.commit()
                        logger.info(f"Phase 6 Recovery: SL_CANCEL_PENDING reconciled -> CLOSED (Broker SL filled).")
                        return "CLOSED"
                except Exception as err:
                    logger.warning(f"Failed broker query during SL_CANCEL_PENDING recovery for Trade ID {trade.id}: {err}")

            return "SL_CANCEL_PENDING"

        # 2. Recover EXIT_PENDING State
        elif current_state == "EXIT_PENDING":
            logger.info(f"Phase 6 Recovery: Reconciling EXIT_PENDING for Trade ID {trade.id}...")
            exit_orders = [o for o in child_orders if getattr(o, "order_role", o.get("order_role") if isinstance(o, dict) else "") in ("EXIT_ALL", "STOPLOSS") and getattr(o, "status", o.get("status") if isinstance(o, dict) else "") in ("PLACED", "SUBMITTED", "OPEN")]
            if exit_orders:
                exit_order = exit_orders[0]
                broker_order_id = getattr(exit_order, "broker_order_id", exit_order.get("broker_order_id") if isinstance(exit_order, dict) else None)
                order_id = getattr(exit_order, "id", exit_order.get("id") if isinstance(exit_order, dict) else None)
                if broker_order_id:
                    try:
                        manager = self.manager_factory()
                        broker_adapter = manager.broker_factory.get_broker(entry_order.broker)
                        order_info = broker_adapter.get_order_history(broker_order_id)
                        broker_status = str(order_info.get("status", "")).upper() if isinstance(order_info, dict) else "UNKNOWN"

                        if broker_status in ("FILLED", "COMPLETE"):
                            trade_repository.update_trade(trade.id, status="CLOSED", position_state="CLOSED", session=session)
                            if order_id:
                                order_repository.update_order(order_id, status="COMPLETE", session=session)
                            if session:
                                session.commit()
                            logger.info(f"Phase 6 Recovery: EXIT_PENDING reconciled -> CLOSED (Software exit filled).")
                            return "CLOSED"
                        elif broker_status in ("CANCELLED", "REJECTED"):
                            trade_repository.update_trade(trade.id, position_state="SOFTWARE_TRAILING_ACTIVE", session=session)
                            if session:
                                session.commit()
                            logger.info(f"Phase 6 Recovery: EXIT_PENDING reconciled -> SOFTWARE_TRAILING_ACTIVE (Exit rejected/cancelled).")
                            return "SOFTWARE_TRAILING_ACTIVE"
                    except Exception as err:
                        logger.warning(f"Failed broker query during EXIT_PENDING recovery for Trade ID {trade.id}: {err}")
            else:
                trade_repository.update_trade(trade.id, position_state="SOFTWARE_TRAILING_ACTIVE", session=session)
                if session:
                    session.commit()
                logger.info(f"Phase 6 Recovery: EXIT_PENDING reconciled -> SOFTWARE_TRAILING_ACTIVE (No exit order in-flight).")
                return "SOFTWARE_TRAILING_ACTIVE"

            return "EXIT_PENDING"

        # 3. Recover TARGET_ORDER_PENDING State
        elif current_state == "TARGET_ORDER_PENDING":
            logger.info(f"Phase 6 Recovery: Reconciling TARGET_ORDER_PENDING for Trade ID {trade.id}...")
            target_orders = [o for o in child_orders if "TARGET" in getattr(o, "order_role", o.get("order_role") if isinstance(o, dict) else "") and getattr(o, "status", o.get("status") if isinstance(o, dict) else "") in ("PLACED", "SUBMITTED", "OPEN")]
            if target_orders:
                target_order = target_orders[0]
                broker_order_id = getattr(target_order, "broker_order_id", target_order.get("broker_order_id") if isinstance(target_order, dict) else None)
                order_id = getattr(target_order, "id", target_order.get("id") if isinstance(target_order, dict) else None)
                qty = getattr(target_order, "quantity", target_order.get("quantity") if isinstance(target_order, dict) else 0)
                if broker_order_id:
                    try:
                        manager = self.manager_factory()
                        broker_adapter = manager.broker_factory.get_broker(entry_order.broker)
                        order_info = broker_adapter.get_order_history(broker_order_id)
                        broker_status = str(order_info.get("status", "")).upper() if isinstance(order_info, dict) else "UNKNOWN"

                        if broker_status in ("FILLED", "COMPLETE"):
                            if order_id:
                                order_repository.update_order(order_id, status="COMPLETE", filled_quantity=qty, session=session)
                            trade_repository.update_trade(trade.id, status="PARTIALLY_CLOSED", position_state="SOFTWARE_TRAILING_ACTIVE", session=session)
                            if session:
                                session.commit()
                            logger.info(f"Phase 6 Recovery: TARGET_ORDER_PENDING reconciled -> SOFTWARE_TRAILING_ACTIVE (Target filled).")
                            return "SOFTWARE_TRAILING_ACTIVE"
                        elif broker_status in ("CANCELLED", "REJECTED"):
                            trade_repository.update_trade(trade.id, position_state="SOFTWARE_TRAILING_ACTIVE", session=session)
                            if session:
                                session.commit()
                            logger.info(f"Phase 6 Recovery: TARGET_ORDER_PENDING reconciled -> SOFTWARE_TRAILING_ACTIVE (Target cancelled/rejected).")
                            return "SOFTWARE_TRAILING_ACTIVE"
                    except Exception as err:
                        logger.warning(f"Failed broker query during TARGET_ORDER_PENDING recovery for Trade ID {trade.id}: {err}")

            return "TARGET_ORDER_PENDING"

        return current_state

