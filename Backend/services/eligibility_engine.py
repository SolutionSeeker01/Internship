# eligibility_engine.py - Core Orchestrator for Client Target Eligibility
'use strict'

from typing import Dict, Any, List
from database.execution_target_repository import (
    get_eligible_candidates,
    bulk_insert_execution_targets
)
from utils.logger import get_logger
from dev_tools.drm import emit_event

logger = get_logger(__name__)

# Execution states matching ExecutionPlanStatus and SkipReason concepts
STATUS_READY = "READY"
STATUS_SKIPPED = "SKIPPED"

SKIP_BROKER_NOT_CONFIGURED = "BROKER_NOT_CONFIGURED"
SKIP_BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
SKIP_ACCESS_TOKEN_MISSING = "ACCESS_TOKEN_MISSING"


def run_eligibility_engine(signal_id: int, strategy_id: int) -> Dict[str, int]:
    """
    Orchestrates the evaluation of client subscription eligibility for a given signal.
    Determines readiness, constructs target records, and bulk persists them.
    
    Args:
        signal_id (int): Database primary key for the incoming signal.
        strategy_id (int): Database primary key for the strategy.
        
    Returns:
        Dict[str, int]: Structured summary execution stats:
            - processed: Total candidates evaluated
            - ready: Total candidates marked READY
            - skipped: Total candidates marked SKIPPED
            - inserted: Total records successfully persisted to DB
    """
    logger.info(f"Starting target eligibility evaluation: Signal ID={signal_id}, Strategy ID={strategy_id}")

    # 1. Retrieve the list of active subscribers for the strategy (DB logic isolated to repo)
    candidates = get_eligible_candidates(strategy_id)
    processed_count = len(candidates)
    
    if processed_count == 0:
        logger.info(f"Target evaluation completed: No active subscribers found for Strategy ID={strategy_id}")
        return {
            "processed": 0,
            "ready": 0,
            "skipped": 0,
            "inserted": 0
        }

    targets_to_persist: List[Dict[str, Any]] = []
    ready_count = 0
    skipped_count = 0

    # 2. Iterate and classify client readiness
    for client in candidates:
        client_id = client["client_id"]
        
        # Classification evaluation flow (headless execution independent of UI dashboard session):
        token = str(client.get("access_token") or "").strip()
        if not client.get("broker_exists"):
            status = STATUS_SKIPPED
            skip_reason = SKIP_BROKER_NOT_CONFIGURED
        elif not token:
            status = STATUS_SKIPPED
            skip_reason = SKIP_ACCESS_TOKEN_MISSING
        else:
            status = STATUS_READY
            skip_reason = None
            
        # Update metrics
        if status == STATUS_READY:
            ready_count += 1
        else:
            skipped_count += 1

        # Construct target execution mapping record
        targets_to_persist.append({
            "signal_id": signal_id,
            "client_id": client_id,
            "status": status,
            "skip_reason": skip_reason
        })

    # 3. Persist targets to the database (transaction boundary handled in repository layer)
    inserted_count = bulk_insert_execution_targets(targets_to_persist)

    logger.info(
        f"Eligibility engine completed for Signal ID={signal_id}. "
        f"Summary: processed={processed_count}, ready={ready_count}, "
        f"skipped={skipped_count}, inserted={inserted_count}"
    )

    emit_event(
        event_type="ELIGIBILITY_COMPLETED",
        component="ELIGIBILITY_ENGINE",
        payload={
            "signal_id": signal_id,
            "strategy_id": strategy_id,
            "processed": processed_count,
            "ready": ready_count,
            "skipped": skipped_count,
            "inserted": inserted_count
        }
    )

    # 4. Return structured operational summary dictionary
    return {
        "processed": processed_count,
        "ready": ready_count,
        "skipped": skipped_count,
        "inserted": inserted_count
    }
