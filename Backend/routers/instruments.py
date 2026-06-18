from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel, Field, validator
import re
import threading
from datetime import date
from typing import List, Dict, Any

from database.instrument_repository import (
    get_all_instruments as db_get_all,
    create_instrument as db_create,
    delete_instrument as db_delete,
    toggle_favorite as db_toggle_favorite,
    get_favorite_instruments as db_get_favorites,
    check_duplicate as db_check_duplicate
)
from market_data.subscriptions import reload_instruments
from market_data.connection import get_kite
from utils.logger import get_logger

logger = get_logger(__name__)

# Daily-expiring cache for exchange instruments
_instruments_cache = {}  # exchange_name -> (date, list_of_instruments)
_cache_lock = threading.Lock()

def normalize_string(val: str) -> str:
    if not val:
        return ""
    return re.sub(r"\s+", " ", val.strip().upper())

router = APIRouter(prefix="/instruments", tags=["instruments"])

# Input validation Regex patterns
SYMBOL_REGEX = re.compile(r"^[A-Z0-9_\-]+$")

class InstrumentCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    token: int = Field(..., gt=0)
    exchange: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    segment: str = Field(..., min_length=1, max_length=50)
    broker: str = Field(..., min_length=1, max_length=50)
    instrument_category: str = Field(default="STOCK")

    @validator("symbol")
    def validate_symbol(cls, v):
        v_upper = v.upper().strip()
        if not SYMBOL_REGEX.match(v_upper):
            raise ValueError("Symbol must be uppercase alphanumeric (dashes and underscores allowed).")
        return v_upper

    @validator("instrument_category")
    def validate_category(cls, v):
        v_upper = v.upper().strip()
        allowed = {"INDEX", "STOCK", "FUTURE", "OPTION", "ETF"}
        if v_upper not in allowed:
            raise ValueError(f"Category must be one of: {allowed}")
        return v_upper

class FavoriteUpdate(BaseModel):
    is_favorite: bool




@router.get("", response_model=List[Dict[str, Any]])
def get_instruments():
    """
    Retrieves all instruments from PostgreSQL. Returns only metadata, no credentials.
    """
    logger.info("GET /instruments requested.")
    return db_get_all()


@router.post("")
def add_instrument(payload: InstrumentCreate):
    """
    Creates/saves a new instrument in PostgreSQL after metadata and live market validation.
    """
    logger.info(f"POST /instruments: {payload.symbol} ({payload.instrument_category})")

    # 1. Duplicate Check
    dup = db_check_duplicate(payload.symbol, payload.token)
    if dup.get("symbol_exists"):
        raise HTTPException(
            status_code=400,
            detail="Instrument with this symbol already exists in database."
        )
    if dup.get("token_exists"):
        raise HTTPException(
            status_code=400,
            detail="Instrument with this token already exists in database."
        )

    # Get authorized KiteConnect instance
    try:
        kite = get_kite()
    except Exception as e:
        logger.error(f"Failed to get KiteConnect instance during validation: {e}")
        raise HTTPException(
            status_code=500,
            detail="Unable to validate instrument at this time."
        )

    # 2. Metadata Validation (with caching)
    exchange_upper = payload.exchange.upper().strip()
    today = date.today()
    
    with _cache_lock:
        cached_date, cached_list = _instruments_cache.get(exchange_upper, (None, None))
        if cached_list is None or cached_date != today:
            logger.info(f"Fetching master instrument list from Zerodha for exchange: {exchange_upper}")
            try:
                fetched_list = kite.instruments(exchange=exchange_upper)
                _instruments_cache[exchange_upper] = (today, fetched_list)
                cached_list = fetched_list
            except Exception as e:
                logger.error(f"Zerodha master list fetch failed for exchange {exchange_upper}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Unable to validate instrument at this time."
                )

    # Find the master record matching the payload.token
    matched_record = None
    for inst in cached_list:
        if inst.get("instrument_token") == payload.token:
            matched_record = inst
            break

    # Debug Log User Input and Matched Record
    logger.info("--- INSTRUMENT VALIDATION DEBUG ---")
    logger.info(f"User Input - Symbol: {payload.symbol}, Token: {payload.token}, Exchange: {payload.exchange}, Name: {payload.name}")
    if matched_record:
        logger.info(f"Matched Zerodha Record - Tradingsymbol: {matched_record.get('tradingsymbol')}, Instrument Token: {matched_record.get('instrument_token')}, Exchange: {matched_record.get('exchange')}, Name: {matched_record.get('name')}, Segment: {matched_record.get('segment')}")
    else:
        logger.info("Matched Zerodha Record: None")

    token_match = "PASS" if matched_record else "FAIL"
    symbol_match = "FAIL"
    exchange_match = "FAIL"
    name_match = "FAIL"

    if matched_record:
        symbol_match = "PASS" if str(matched_record.get("tradingsymbol") or "").upper() == payload.symbol.upper() else "FAIL"
        exchange_match = "PASS" if str(matched_record.get("exchange") or "").upper() == exchange_upper else "FAIL"
        
        user_name_norm = normalize_string(payload.name)
        zerodha_name_norm = normalize_string(str(matched_record.get("name") or ""))
        print(f"DEBUG Name Comparison: repr(user_name)={repr(payload.name)}, repr(zerodha_name)={repr(matched_record.get('name'))}")
        logger.info(f"DEBUG Name Comparison: repr(user_name)={repr(payload.name)}, repr(zerodha_name)={repr(matched_record.get('name'))}")
        name_match = "PASS" if user_name_norm == zerodha_name_norm else "FAIL"

    logger.info(f"Token Match: {token_match}")
    logger.info(f"Symbol Match: {symbol_match}")
    logger.info(f"Exchange Match: {exchange_match}")
    logger.info(f"Name Match: {name_match}")
    logger.info("----------------------------------")

    if not matched_record:
        raise HTTPException(
            status_code=400,
            detail="Symbol, token, exchange, or name does not match Zerodha records."
        )

    # Strict check: exchange and tradingsymbol must match Zerodha record exactly
    if str(matched_record.get("exchange") or "").upper() != exchange_upper or \
       str(matched_record.get("tradingsymbol") or "").upper() != payload.symbol.upper():
        raise HTTPException(
            status_code=400,
            detail="Symbol, token, exchange, or name does not match Zerodha records."
        )

    # Loose check: instrument name comparison (normalized whitespace/casing/trimming)
    if normalize_string(payload.name) != normalize_string(str(matched_record.get("name") or "")):
        raise HTTPException(
            status_code=400,
            detail="Symbol, token, exchange, or name does not match Zerodha records."
        )

    # 3. Live Market Validation using authoritative fields from matched record
    auth_exchange = matched_record.get("exchange")
    auth_symbol = matched_record.get("tradingsymbol")
    query_symbol = f"{auth_exchange}:{auth_symbol}"

    try:
        ltp_res = kite.ltp(query_symbol)
        if not ltp_res or query_symbol not in ltp_res:
            raise HTTPException(
                status_code=400,
                detail="Instrument exists but live market data could not be verified."
            )
        
        last_price = ltp_res[query_symbol].get("last_price")
        if last_price is None or not isinstance(last_price, (int, float)) or last_price <= 0:
            raise HTTPException(
                status_code=400,
                detail="Instrument exists but live market data could not be verified."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Live market LTP validation failed for {query_symbol}: {e}")
        raise HTTPException(
            status_code=400,
            detail="Instrument exists but live market data could not be verified."
        )

    # 4. Insert into database using Zerodha master record fields as the source of truth
    success = db_create(
        symbol=str(matched_record.get("tradingsymbol") or payload.symbol).upper().strip(),
        token=int(matched_record.get("instrument_token") or payload.token),
        exchange=str(matched_record.get("exchange") or payload.exchange).upper().strip(),
        name=str(matched_record.get("name") or payload.name).strip(),
        segment=str(matched_record.get("segment") or payload.segment).strip(),
        broker=payload.broker.strip(),
        instrument_category=payload.instrument_category
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write instrument to database.")

    # Refresh instrument cache and update active subscriptions
    try:
        reload_instruments()
        from market_data.kite_client import update_subscriptions
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache or update subscriptions: {e}")

    return {"status": "success", "message": f"Instrument '{payload.symbol}' created successfully."}


@router.delete("/{symbol}")
def delete_instrument(symbol: str = Path(..., min_length=1)):
    """
    Deletes an instrument from PostgreSQL and reloads the active subscriptions cache.
    """
    symbol_upper = symbol.upper().strip()
    logger.info(f"DELETE /instruments/{symbol_upper}")
    success = db_delete(symbol_upper)
    if not success:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol_upper}' not found.")

    # Refresh instrument cache and update active subscriptions
    try:
        reload_instruments()
        from market_data.kite_client import update_subscriptions
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache or update subscriptions: {e}")

    return {"status": "success", "message": f"Instrument '{symbol_upper}' deleted successfully."}


@router.patch("/{symbol}/favorite")
def toggle_favorite(
    symbol: str = Path(..., min_length=1),
    payload: FavoriteUpdate = Body(...)
):
    """
    Toggles/updates favorite status of an instrument and refreshes the cache.
    """
    symbol_upper = symbol.upper().strip()
    logger.info(f"PATCH /instruments/{symbol_upper}/favorite -> {payload.is_favorite}")
    success = db_toggle_favorite(symbol_upper, payload.is_favorite)
    if not success:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol_upper}' not found.")

    # Refresh instrument cache
    try:
        reload_instruments()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache (it might be empty of active items): {e}")

    return {"status": "success", "message": f"Instrument '{symbol_upper}' favorite set to {payload.is_favorite}."}





@router.get("/favorites", response_model=List[Dict[str, Any]])
def get_favorite_instruments():
    """
    Retrieves all instruments that are active and marked as favorite.
    """
    logger.info("GET /instruments/favorites requested.")
    return db_get_favorites()
