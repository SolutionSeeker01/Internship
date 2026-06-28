import os
import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, status
from utils.logger import get_logger
from signals.schemas import WebhookSignalRequest
from market_data.lookup import get_market_price, BrokerUnavailableException
from database.signal_repository import check_duplicate_signal

logger = get_logger(__name__)

# Configurable constants
MAX_LTP_DEVIATION_PCT = 10.0  # 10%


from market_data.universe import is_symbol_in_universe, is_universe_cache_empty

def validate_signal(signal: WebhookSignalRequest) -> tuple:
    """
    Performs layered business rule and market sanity validations on incoming signals.
    
    Flow:
    1. Secret Validation (handled by Router)
    2. Payload Validation (handled by Pydantic)
    3. Timestamp Validation (expired or in future)
    4. Trading Logic Validation (SL direction)
    5. Universe Cache Validation (Symbol exists in universe)
    6. Market Price Validation (Price sanity deviation check, partial validation on timeout/outage)
    7. Duplicate Detection (no matching symbol+action+entry within 2 minutes)
    """
    symbol = signal.symbol
    action = signal.action
    entry = signal.entry
    sl = signal.sl
    ts = signal.ts

    logger.debug(f"Starting layered business rule validation for signal: {action} {symbol} Entry={entry} SL={sl} TS={ts}")

    # --- Layer 3: Timestamp Validation ---
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

    # --- Layer 4: Trading Logic Validation ---
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

    # --- Layer 5: Universe Cache Validation & Layer 6: Market Price Validation ---
    cache_empty = is_universe_cache_empty()
    symbol_in_cache = is_symbol_in_universe(symbol) if not cache_empty else False

    # Rule B: Cache populated, symbol missing from cache -> REJECT
    if not cache_empty and not symbol_in_cache:
        logger.warning(f"Rejected signal due to validation failure: SYMBOL_NOT_IN_UNIVERSE for symbol '{symbol}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid symbol. Symbol not found in instrument universe."
        )

    validation_status = "VALIDATED"
    validation_reason = None

    try:
        current_ltp = get_market_price(symbol)
        if current_ltp is not None and current_ltp > 0:
            # Rule C / Normal: LTP retrieved successfully, perform sanity checks
            deviation = abs(entry - current_ltp) / current_ltp * 100
            if deviation > MAX_LTP_DEVIATION_PCT:
                logger.warning("Rejected signal due to validation failure: ENTRY_LTP_MISMATCH")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Entry price too far from market price"
                )
        else:
            # get_market_price returned None (broker is online but symbol lookup returned nothing)
            if cache_empty:
                # Rule C (LTP lookup failed when online) -> REJECT
                logger.warning(f"Rejected signal due to validation failure: SYMBOL_NOT_FOUND_ON_BROKER for symbol '{symbol}'")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid symbol. Symbol not found by broker."
                )
            else:
                # Rule A: Cache populated, symbol exists in cache, LTP is None -> PARTIAL
                logger.warning(f"LTP unavailable for symbol '{symbol}'. Entering partial validation mode.")
                validation_status = "PARTIAL"
                validation_reason = "LTP_UNAVAILABLE"

    except BrokerUnavailableException:
        if cache_empty:
            # Rule D: Cache empty and broker is unavailable -> REJECT
            logger.warning(f"Rejected signal: Instrument universe unavailable and broker verification unavailable for symbol '{symbol}'")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to validate signal. Instrument universe unavailable and broker verification unavailable."
            )
        else:
            # Rule A: Cache populated, symbol exists in cache, broker throws error -> PARTIAL
            logger.warning(f"LTP lookup failed (broker unavailable) for symbol '{symbol}' in cache. Entering partial validation mode.")
            validation_status = "PARTIAL"
            validation_reason = "LTP_UNAVAILABLE"
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during LTP validation for {symbol}: {e}")
        if cache_empty:
            logger.warning(f"Rejected signal due to unexpected lookup failure: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to validate signal. Instrument universe unavailable and broker verification unavailable."
            )
        else:
            validation_status = "PARTIAL"
            validation_reason = "LTP_UNAVAILABLE"

    # --- Layer 7: Duplicate Signal Protection ---
    if check_duplicate_signal(symbol, action, entry):
        logger.warning("Rejected signal due to validation failure: DUPLICATE_SIGNAL")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate signal detected"
        )

    logger.info(f"Signal {action} {symbol} successfully validated against business rules. Status={validation_status} Reason={validation_reason}")
    return validation_status, validation_reason
