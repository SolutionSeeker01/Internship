# runtime_validator.py - Runtime Validator Service
'use strict'

from datetime import datetime
from typing import Optional
from models.execution_context import ExecutionContext
from models.execution_result import ExecutionResult, create_rejection_result


def validate_runtime_context(context: ExecutionContext) -> Optional[ExecutionResult]:
    """
    Validates that execution may proceed using the assembled ExecutionContext.
    
    Implements Section 5.6 (Runtime Validator) of the Architecture Reference.
    """
    # Rule 1: fetched_at not stale (< 15 seconds)
    now = datetime.now(context.fetched_at.tzinfo) if context.fetched_at.tzinfo else datetime.now()
    staleness_seconds = (now - context.fetched_at).total_seconds()
    if staleness_seconds > 15.0:
        return create_rejection_result(
            context,
            outcome="RUNTIME_REJECTED",
            fail_reason=f"CONTEXT_STALE: fetched_at was {staleness_seconds:.1f}s ago (>15s)"
        )

    # Rule 2: session_valid == True
    if not context.session_valid:
        return create_rejection_result(
            context,
            outcome="RUNTIME_REJECTED",
            fail_reason="BROKER_SESSION_INVALID"
        )

    # Rule 3: market_open == True
    if not context.market_open:
        return create_rejection_result(
            context,
            outcome="RUNTIME_REJECTED",
            fail_reason="MARKET_CLOSED"
        )

    # Rule 4: exchange_status == "NORMAL"
    if context.exchange_status != "NORMAL":
        return create_rejection_result(
            context,
            outcome="RUNTIME_REJECTED",
            fail_reason=f"EXCHANGE_HALTED: status is '{context.exchange_status}'"
        )

    # PASS -> Return None
    return None
