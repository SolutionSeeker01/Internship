import os
from fastapi import APIRouter, HTTPException, status
from signals.schemas import WebhookSignalRequest
from signals.validator import validate_signal
from database.signal_repository import save_signal
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/webhook", status_code=status.HTTP_201_CREATED)
async def webhook_ingest(payload: WebhookSignalRequest) -> dict:
    """
    Ingests, validates, and persists incoming third-party trading signals.

    Flow:
    Router -> Validator -> Repository -> Database.

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

    # 2. Run business rules validator
    if not validate_signal(payload):
        logger.warning(f"Rejected signal ingestion due to validation failures on symbol: {payload.symbol}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bad Request: Signal failed business rule validations."
        )

    # 3. Save the validated signal to the repository
    success = save_signal(
        action=payload.action,
        symbol=payload.symbol,
        entry=payload.entry,
        sl=payload.sl,
        timeframe=payload.tf,
        timestamp=payload.ts
    )

    if not success:
        logger.error(f"Failed to persist validated signal to database: {payload.symbol}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database persistence failure."
        )

    return {
        "status": "success",
        "message": "Signal successfully validated and persisted."
    }
