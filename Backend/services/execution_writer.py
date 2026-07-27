# execution_writer.py - Execution Writer Service
'use strict'

from typing import Optional, Any
from database.execution_writer_repository import record_execution_result
from models.execution_result import ExecutionResult
from utils.logger import get_logger

logger = get_logger(__name__)


def write_execution_result(
    execution_result: ExecutionResult,
    order_spec: Optional[Any] = None
) -> ExecutionResult:
    """
    Translates an ExecutionResult into database updates and a structured log entry.
    
    Implements Section 5.13 (Execution Writer) of the Architecture Reference v1.3.
    
    Actions:
      1. Update `signal_execution_targets` status to final state (SUBMITTED, RUNTIME_REJECTED, RISK_REJECTED, FAILED).
      2. If outcome == 'SUBMITTED', create `orders` row with broker_order_id.
      3. Emit structured audit log entry for every outcome.
      
    Constraints:
      - Contains NO business logic
      - Translates ExecutionResult to persistence and structured logging only
    """
    target_id = getattr(execution_result, "execution_target_id", 0)
    signal_id = getattr(execution_result, "signal_id", 0)
    client_id = getattr(execution_result, "client_id", 0)
    outcome = getattr(execution_result, "outcome", "INTERNAL_ERROR")
    broker_order_id = getattr(execution_result, "broker_order_id", None)
    fail_reason = getattr(execution_result, "fail_reason", None)

    # 1. Emit Structured Audit Log Entry (Section 5.13 Action 3)
    if outcome == "SUBMITTED":
        logger.info(
            f"[EXECUTION_SUCCESS] target_id={target_id} signal_id={signal_id} client_id={client_id} "
            f"outcome={outcome} broker_order_id={broker_order_id}"
        )
    else:
        logger.warning(
            f"[EXECUTION_REJECTED] target_id={target_id} signal_id={signal_id} client_id={client_id} "
            f"outcome={outcome} fail_reason={fail_reason}"
        )

    # 2. Persist to Database (Section 5.13 Action 1 & 2)
    try:
        record_execution_result(execution_result, order_spec=order_spec)
    except Exception as err:
        logger.error(f"Execution Writer failed to persist result for target ID {target_id}: {err}")
        # Re-raise: swallowing this exception leaves signal_execution_targets stuck in EXECUTING
        # state, which causes StartupRecoveryService to re-feed the target and potentially
        # double-place the same order on the next server restart.
        raise

    # Return passive ExecutionResult DTO
    return execution_result
