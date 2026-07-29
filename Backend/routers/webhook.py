import os
from fastapi import APIRouter, HTTPException, status
from signals.schemas import WebhookSignalRequest
from signals.validator import validate_signal
from database.signal_repository import save_signal, save_signal_and_return_id
from services.signal_engine import calculate_targets
from services.eligibility_engine import run_eligibility_engine
from utils.logger import get_logger
from dev_tools.drm import emit_event

logger = get_logger(__name__)

router = APIRouter()


@router.post("/webhook", status_code=status.HTTP_201_CREATED)
async def webhook_ingest(payload: WebhookSignalRequest) -> dict:
    """
    Ingests, validates, and persists incoming third-party trading signals.

    Flow:
    Router -> Validator -> Repository -> Database -> Eligibility Engine -> Targets.

    Args:
        payload (WebhookSignalRequest): Normalized request body.

    Returns:
        dict: Ingestion success payload.
    """
    # 1. Validate incoming webhook secret credentials
    expected_secret = os.getenv("WEBHOOK_SECRET")
    if not expected_secret or payload.secret != expected_secret:
        logger.warning("Rejected unauthorized webhook access attempt due to invalid secret credential.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid secret credential."
        )

    # Instrument: Emit SIGNAL_RECEIVED event
    emit_event(
        event_type="SIGNAL_RECEIVED",
        component="WEBHOOK_ROUTER",
        payload={
            "symbol": payload.symbol,
            "action": payload.action,
            "entry": float(payload.entry),
            "sl": float(payload.sl),
            "source": "WEBHOOK"
        }
    )

    # 2. Run business rules validator
    try:
        val_status, val_reason = validate_signal(payload)

        # 3. Calculate targets for accepted signals before persistence
        t1, t2, t3 = None, None, None
        try:
            targets = calculate_targets(
                action=payload.action,
                entry=payload.entry,
                stoploss=payload.sl,
            )
            t1, t2, t3 = targets.t1, targets.t2, targets.t3
        except Exception as calc_err:
            logger.error(f"Target calculation failed for {payload.symbol}: {calc_err}")
            # Fail fast: do not silently persist a signal without targets
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Signal accepted but target calculation failed."
            )

        # 4. Save the validated signal with pre-calculated targets and return the primary key ID
        signal_id = save_signal_and_return_id(
            action=payload.action,
            symbol=payload.symbol,
            entry=payload.entry,
            sl=payload.sl,
            timeframe=payload.tf,
            timestamp=payload.ts,
            status="PENDING",
            validation_status=val_status,
            validation_reason=val_reason,
            t1=t1,
            t2=t2,
            t3=t3,
            strategy_id=payload.strategy_id,
        )

        # 5. Run the target eligibility engine for fully VALIDATED signals (only if a strategy is linked)
        # PARTIAL signals (e.g. LTP unavailable) are persisted for audit record but skipped from automatic execution.
        if payload.strategy_id is not None:
            if val_status == "VALIDATED":
                try:
                    run_eligibility_engine(signal_id=signal_id, strategy_id=payload.strategy_id)
                except Exception as engine_err:
                    logger.error(
                        f"Eligibility engine failed for Signal ID {signal_id} "
                        f"(strategy_id={payload.strategy_id}): {engine_err}"
                    )
            else:
                logger.warning(
                    f"Signal ID {signal_id} skipped automatic execution because validation status is '{val_status}' "
                    f"(reason: '{val_reason}')."
                )

    except HTTPException as http_ex:
        # Check if the error is a 401 Unauthorized for secret credentials.
        # Unauthorized secret checks shouldn't write to the database.
        if http_ex.status_code == status.HTTP_401_UNAUTHORIZED:
            raise
            
        # Persist the rejected signal to database
        try:
            save_signal(
                action=payload.action,
                symbol=payload.symbol,
                entry=payload.entry,
                sl=payload.sl,
                timeframe=payload.tf,
                timestamp=payload.ts,
                status="CANCELLED",
                validation_status="REJECTED",
                validation_reason=http_ex.detail,
                strategy_id=payload.strategy_id,
            )
        except Exception as db_err:
            logger.error(f"Failed to persist rejected signal to database: {db_err}")
            
        # Re-raise the original HTTPException to keep webhook client response identical
        raise http_ex

    return {
        "status": "success",
        "message": "Signal successfully validated and persisted."
    }
