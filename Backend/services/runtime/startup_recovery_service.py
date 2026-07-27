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
        subscription_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Args:
            registry (OrderManagerRegistry): The active in-memory trade manager registry.
            manager_factory (Callable[[], Any]): Required injected factory/callback responsible for
                creating initialized OrderManagerService instances.
            subscription_callback (Optional[Callable[[str], None]]): Optional callback function
                invoked to request symbol tick feed subscription when an active trade is restored.
        """
        if registry is None:
            raise ValueError("registry is required for StartupRecoveryService.")
        if manager_factory is None:
            raise ValueError("manager_factory is required for StartupRecoveryService.")

        self.registry = registry
        self.manager_factory = manager_factory
        self.subscription_callback = subscription_callback

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

            for trade in open_trades:
                trade_id = trade.id
                try:
                    self._recover_single_active_trade(trade, session=db, subscribed_symbols=trade_results["subscribed_symbols"])
                    trade_results["reconstructed_trades"] += 1
                except Exception as trade_err:
                    trade_results["failed_trades"] += 1
                    logger.error(f"Failed to recover active Trade ID {trade_id}: {trade_err}", exc_info=True)

            summary = {
                "status": "COMPLETED",
                "orphaned_targets_found": len(orphaned_targets),
                "target_outcomes": target_results,
                "active_trades_found": len(open_trades),
                "reconstructed_trades": trade_results["reconstructed_trades"],
                "failed_trades": trade_results["failed_trades"],
                "subscribed_symbols": list(trade_results["subscribed_symbols"])
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

        # 2. Invoke position_state_reconstructor (Pure Phase 6 module)
        state: ReconstructedPositionState = reconstruct_position_state(
            trade_id=trade_id,
            execution_target_id=execution_target_id,
            entry_filled_qty=entry_filled_qty,
            trade_status=trade.status,
            trailing_sl_activated=trade.trailing_sl_activated,
            child_orders=child_order_dicts
        )

        if state.position_state == "CLOSED":
            logger.warning(f"Trade ID {trade_id} evaluates to CLOSED during reconstruction. Skipping registry registration.")
            return

        # 3. Instantiate OrderManagerService via injected manager_factory
        manager_instance = self.manager_factory()

        # 4. Register in OrderManagerRegistry
        symbol = entry_order.symbol
        
        self.registry.register_trade(
            trade_id=trade_id,
            symbol=symbol,
            manager_instance=manager_instance
        )

        # 5. Trigger symbol subscription callback
        symbol_upper = symbol.strip().upper()
        subscribed_symbols.add(symbol_upper)

        if self.subscription_callback:
            try:
                self.subscription_callback(symbol_upper)
            except Exception as sub_err:
                logger.error(f"Subscription callback failed for symbol '{symbol_upper}' on Trade ID {trade_id}: {sub_err}")

        logger.info(
            f"Restored Trade ID {trade_id} into registry (State: '{state.position_state}', "
            f"Symbol: '{symbol_upper}', Trailing Activated: {state.trailing_sl_activated})."
        )
