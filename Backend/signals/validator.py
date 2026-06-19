import os
import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, status
from utils.logger import get_logger
from signals.schemas import WebhookSignalRequest
from market_data.lookup import get_market_price
from database.signal_repository import check_duplicate_signal

logger = get_logger(__name__)

# Configurable constants
SL_MAX_DISTANCE_PCT = 0.20  # 20%
MAX_LTP_DEVIATION_PCT = 10.0  # 10%


def validate_signal(signal: WebhookSignalRequest) -> bool:
    """
    Performs layered business rule and market sanity validations on incoming signals.
    
    Layers:
    1. Payload Validation (handled by Pydantic)
    2. Timestamp Validation (expired or in future)
    3. Trading Logic Validation (SL direction, max 20% distance)
    4. Market Sanity Validation (optional LTP check within 10%)
    5. Duplicate Signal Protection (no matching symbol+action+entry within 2 minutes)
    6. Market Hours Validation (weekday check, 9:15-15:30 IST)
    """
    symbol = signal.symbol
    action = signal.action
    entry = signal.entry
    sl = signal.sl
    ts = signal.ts

    logger.debug(f"Starting layered business rule validation for signal: {action} {symbol} Entry={entry} SL={sl} TS={ts}")

    # --- Layer 2: Timestamp Validation ---
    now_ms = int(time.time() * 1000)
    
    # Reject signal older than 10 minutes
    if now_ms - ts > 600000:
        logger.warning("Rejected signal due to validation failure: TIMESTAMP_EXPIRED")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signal expired"
        )
        
    # Reject future timestamps (allow clock drift of 60 seconds)
    if ts > now_ms + 60000:
        logger.warning("Rejected signal due to validation failure: TIMESTAMP_IN_FUTURE")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signal timestamp in future"
        )

    # --- Layer 3: Trading Logic Validation ---
    if action == "BUY":
        if sl >= entry:
            logger.warning("Rejected signal due to validation failure: INVALID_STOPLOSS")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stoploss: Stoploss must be strictly below entry price for BUY."
            )
    elif action == "SELL":
        if sl <= entry:
            logger.warning("Rejected signal due to validation failure: INVALID_STOPLOSS")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stoploss: Stoploss must be strictly above entry price for SELL."
            )
            
    # Stoploss distance check (max 20% of entry price)
    sl_distance = abs(entry - sl) / entry
    if sl_distance > SL_MAX_DISTANCE_PCT:
        logger.warning("Rejected signal due to validation failure: INVALID_STOPLOSS")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid stoploss: Stoploss distance cannot exceed 20% of entry price."
        )

    # --- Layer 4: Market Sanity Validation ---
    try:
        current_ltp = get_market_price(symbol)
        if current_ltp is not None and current_ltp > 0:
            deviation = abs(entry - current_ltp) / current_ltp * 100
            if deviation > MAX_LTP_DEVIATION_PCT:
                logger.warning("Rejected signal due to validation failure: ENTRY_LTP_MISMATCH")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Entry price too far from market price"
                )
        else:
            logger.warning(f"LTP unavailable for symbol '{symbol}'. Market sanity validation skipped.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during LTP validation for {symbol}: {e}")
        logger.warning(f"LTP unavailable for symbol '{symbol}'. Market sanity validation skipped.")

    # --- Layer 5: Duplicate Signal Protection ---
    if check_duplicate_signal(symbol, action, entry):
        logger.warning("Rejected signal due to validation failure: DUPLICATE_SIGNAL")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate signal detected"
        )

    # --- Layer 6: Market Hours Validation ---
    if os.getenv("DISABLE_MARKET_HOURS_CHECK", "false").lower() != "true":
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        # Convert signal timestamp (ts) to IST datetime
        signal_time_ist = datetime.fromtimestamp(ts / 1000.0, tz=ist_tz)
        
        # Check weekend
        if signal_time_ist.weekday() in (5, 6):
            logger.warning("Rejected signal due to validation failure: MARKET_CLOSED")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Market is closed on weekends"
            )
            
        # Check trading hours (9:15 AM to 3:30 PM IST)
        market_start = signal_time_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = signal_time_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        if not (market_start <= signal_time_ist <= market_end):
            logger.warning("Rejected signal due to validation failure: MARKET_CLOSED")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Outside equity trading hours"
            )

    logger.info(f"Signal {action} {symbol} successfully validated against business rules.")
    return True
