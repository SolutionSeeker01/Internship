import os
import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, status
from utils.logger import get_logger
from signals.schemas import WebhookSignalRequest
from market_data.lookup import get_market_price, BrokerUnavailableException, InvalidSymbolException
from database.signal_repository import check_duplicate_signal

logger = get_logger(__name__)

# Configurable constants
MAX_LTP_DEVIATION_PCT = 10.0  # 10%


from database.instrument_repository import is_instrument_catalog_empty, find_instrument

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

    # --- Layer 1: Strategy Catalog Existence Validation ---
    if signal.strategy_id is not None:
        from database.db import SessionLocal
        from sqlalchemy.sql import text
        session = SessionLocal()
        try:
            exists = session.execute(
                text("SELECT id FROM strategies WHERE id = :id"),
                {"id": signal.strategy_id}
            ).fetchone()
            if not exists:
                logger.warning(f"Rejected signal due to validation failure: STRATEGY_NOT_FOUND for strategy_id {signal.strategy_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid strategy ID: Strategy {signal.strategy_id} does not exist in catalog."
                )
        finally:
            session.close()

    # --- Layer 2: Market Service Connectivity Validation ---
    from market_data.kite_client import is_market_service_running
    if not is_market_service_running():
        logger.warning("Rejected signal due to validation failure: MASTER_OFFLINE")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signal rejected: No active MASTER broker session."
        )

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
        sl_dist_pct = ((entry - sl) / entry) * 100.0
        if sl_dist_pct > 5.0:
            logger.warning(f"Rejected signal due to validation failure: STOPLOSS_EXCEEDS_MAX_DISTANCE ({sl_dist_pct:.2f}% > 5.0%)")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stoploss: Stoploss distance ({sl_dist_pct:.2f}%) exceeds maximum allowed threshold of 5.0%."
            )
    elif action == "SELL":
        if sl <= entry:
            logger.warning("Rejected signal due to validation failure: INVALID_STOPLOSS")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid stoploss: Stoploss must be strictly above entry price for SELL."
            )
        sl_dist_pct = ((sl - entry) / entry) * 100.0
        if sl_dist_pct > 5.0:
            logger.warning(f"Rejected signal due to validation failure: STOPLOSS_EXCEEDS_MAX_DISTANCE ({sl_dist_pct:.2f}% > 5.0%)")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid stoploss: Stoploss distance ({sl_dist_pct:.2f}%) exceeds maximum allowed threshold of 5.0%."
            )


    # --- Layer 5: Market Price and Symbol Validation (Primary) ---
    validation_status = "VALIDATED"
    validation_reason = None
    cache_empty = is_instrument_catalog_empty()

    try:
        current_ltp = get_market_price(symbol)
        if current_ltp is not None and current_ltp > 0:
            # Case 1: LTP retrieved successfully, perform sanity checks
            deviation = abs(entry - current_ltp) / current_ltp * 100
            if deviation > MAX_LTP_DEVIATION_PCT:
                logger.warning("Rejected signal due to validation failure: ENTRY_LTP_MISMATCH")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Entry price too far from market price"
                )
        else:
            # get_market_price returned None (symbol lookup explicitly failed on an online broker)
            # Fall back to PostgreSQL database to check if symbol is valid locally
            symbol_in_db = (find_instrument(symbol) is not None) if not cache_empty else False
            if cache_empty or not symbol_in_db:
                # Symbol is completely unknown to both the broker and database -> REJECT
                logger.warning(f"Rejected signal due to validation failure: SYMBOL_NOT_FOUND_ON_BROKER for symbol '{symbol}'")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid symbol. Symbol not found by broker."
                )
            else:
                # Symbol is locally known but broker returned empty -> PARTIAL
                logger.warning(f"LTP unavailable for symbol '{symbol}' (found in DB). Entering partial validation mode.")
                validation_status = "PARTIAL"
                validation_reason = "LTP_UNAVAILABLE"

    except InvalidSymbolException:
        # Invalid symbol returned explicitly by the broker -> REJECT immediately (do not check DB)
        logger.warning(f"Rejected signal due to validation failure: INVALID_SYMBOL_ON_BROKER for symbol '{symbol}'")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid symbol. Symbol not found by broker."
        )
    except BrokerUnavailableException:
        # Case 2: Broker is offline or timed out
        # Fall back to PostgreSQL to verify if the symbol is valid locally
        symbol_in_db = (find_instrument(symbol) is not None) if not cache_empty else False
        if cache_empty or not symbol_in_db:
            # Broker is offline and symbol is unknown locally -> REJECT
            logger.warning(f"Rejected signal: Instrument universe unavailable and broker verification unavailable for symbol '{symbol}'")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to validate signal. Instrument universe unavailable and broker verification unavailable."
            )
        else:
            # Broker is offline but symbol is known locally -> PARTIAL validation
            logger.warning(f"LTP lookup failed (broker unavailable) for symbol '{symbol}' in cache. Entering partial validation mode.")
            validation_status = "PARTIAL"
            validation_reason = "LTP_UNAVAILABLE"
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during LTP validation for {symbol}: {e}")
        symbol_in_db = (find_instrument(symbol) is not None) if not cache_empty else False
        if cache_empty or not symbol_in_db:
            logger.warning(f"Rejected signal due to unexpected lookup failure: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to validate signal. Instrument universe unavailable and broker verification unavailable."
            )
        else:
            validation_status = "PARTIAL"
            validation_reason = "LTP_UNAVAILABLE"

    # --- Layer 7: Duplicate Signal Protection ---
    if check_duplicate_signal(
        symbol=symbol,
        action=action,
        entry=entry,
        sl=sl,
        tf=signal.tf,
        strategy_id=signal.strategy_id
    ):
        logger.warning("Rejected signal due to validation failure: DUPLICATE_SIGNAL")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate signal detected"
        )

    logger.info(f"Signal {action} {symbol} successfully validated against business rules. Status={validation_status} Reason={validation_reason}")
    return validation_status, validation_reason
