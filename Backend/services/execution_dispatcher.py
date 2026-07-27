# Backend/services/execution_dispatcher.py
"""
Execution Dispatcher Service — Background Target Polling & Pipeline Dispatcher

Implements Section 5.3 of ARCHITECTURE_REFERENCE.md (v1.4).

Responsibilities:
  1. Periodically polls the database for `READY` execution targets (`fetch_ready_target_ids`).
  2. Atomically claims each target (`claim_execution_target`), shifting status from `READY` -> `EXECUTING`.
  3. Constructs and executes the `TradeEngine` pipeline (`trade_engine.execute(claimed_target)`).
  4. Operates in a non-blocking background daemon thread during application lifespan.

Constraints:
  - Webhook endpoint remains strictly ingestion-only (never calls TradeEngine directly).
  - Dispatcher is the SOLE consumer responsible for triggering TradeEngine execution.
  - Zero business logic, risk calculations, or order sizing (delegated to TradeEngine stages).
"""

import time
import threading
from typing import Optional, Callable, Dict, Any
from database.execution_target_repository import fetch_ready_target_ids, claim_ready_execution_target
from services.trade_engine import TradeEngine
from models.execution_context import ExecutionContext
from models.risk_budget import RiskBudget
from models.order_quantity import OrderQuantity
from models.order_spec import OrderSpec
from models.execution_result import ExecutionResult
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutionDispatcher:
    """
    Background polling service that claims READY targets and invokes TradeEngine pipeline.
    """

    def __init__(self, poll_interval_seconds: float = 0.5):
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts background dispatcher polling loop in a daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._poll_loop,
                name="ExecutionDispatcherWorker",
                daemon=True
            )
            self._worker_thread.start()
            logger.info("Execution Dispatcher worker thread started.")

    def stop(self) -> None:
        """Stops background dispatcher polling loop cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        logger.info("Execution Dispatcher worker thread stopped.")

    def _poll_loop(self) -> None:
        """Continuous polling loop executing READY target processing."""
        while self._running:
            try:
                self.process_pending_targets()
            except Exception as loop_err:
                logger.error(f"Unexpected error in Execution Dispatcher loop: {loop_err}", exc_info=True)
            
            time.sleep(self.poll_interval)

    def process_pending_targets(self) -> int:
        """
        Polls for READY target IDs, claims them atomically, and processes via TradeEngine.
        Returns count of targets processed in this cycle.
        """
        try:
            target_ids = fetch_ready_target_ids(limit=10)
        except Exception as db_err:
            logger.error(f"Execution Dispatcher failed to fetch READY targets: {db_err}")
            return 0

        if not target_ids:
            return 0

        logger.info(f"Execution Dispatcher found {len(target_ids)} READY target(s) to process.")
        processed_count = 0

        for target_id in target_ids:
            if not self._running:
                break

            # 1. Atomic claim: READY -> EXECUTING
            claimed_target = claim_ready_execution_target(target_id)
            if not claimed_target:
                # Target was claimed by another worker or is no longer READY
                continue

            # 2. Build default TradeEngine instance for execution
            trade_engine = self._create_default_trade_engine()

            # 3. Dispatch to TradeEngine pipeline (Stages 4 -> 7)
            try:
                logger.info(f"Execution Dispatcher invoking TradeEngine for claimed target ID {target_id}...")
                trade_engine.execute(claimed_target)
                processed_count += 1
            except Exception as exec_err:
                logger.error(f"Execution Dispatcher error processing target ID {target_id}: {exec_err}", exc_info=True)

        return processed_count

    def _create_default_trade_engine(self) -> TradeEngine:
        """
        Constructs a standard TradeEngine instance with production stage dependencies.
        """
        from services.execution_context_builder import build_execution_context
        from services.runtime_validator import validate_runtime_context
        from services.risk_manager import evaluate_risk
        from services.quantity_calculator import calculate_order_quantity
        from services.order_builder import build_order_spec
        from services.broker_dispatcher import dispatch_order
        from services.execution_writer import write_execution_result

        return TradeEngine(
            context_builder=build_execution_context,
            runtime_validator=validate_runtime_context,
            risk_manager=evaluate_risk,
            quantity_calculator=calculate_order_quantity,
            order_builder=build_order_spec,
            broker_dispatcher=dispatch_order,
            execution_writer=write_execution_result
        )


# Singleton instance for application lifecycle management
global_execution_dispatcher = ExecutionDispatcher()
