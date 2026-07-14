from fastapi import APIRouter, HTTPException, Path, Body, Depends, Request
from pydantic import BaseModel, Field, validator
import re
import threading
from datetime import date
from typing import List, Dict, Any, Optional

from dependencies.auth import get_current_user
from models.user import User
from models.broker_account import BrokerAccount
from database.db import SessionLocal
from security.encryption import decrypt_value
from services.brokers.factory import BrokerFactory

from database.instrument_repository import (
    get_all_instruments as db_get_all,
    create_instrument as db_create,
    delete_instrument as db_delete,
    delete_instruments_bulk as db_delete_bulk,
    check_duplicate as db_check_duplicate,
    search_instruments as db_search,
    upsert_instruments_bulk as db_upsert_bulk,
    delete_all_instruments as db_delete_all,
    get_instrument_by_symbol_exchange as db_get_instrument,
    get_instrument_by_symbol as db_get_instrument_by_symbol
)
from market_data.subscriptions import reload_instruments
from utils.logger import get_logger
from schemas.instrument_delete import BulkDeleteRequest


logger = get_logger(__name__)

# Daily-expiring cache for exchange instruments
_instruments_cache = {}  # exchange_name -> (date, list_of_instruments)
_cache_lock = threading.Lock()

def normalize_string(val: str) -> str:
    if not val:
        return ""
    return re.sub(r"\s+", " ", val.strip().upper())

def normalize_segment_and_category(segment: str, instrument_type: str) -> tuple:
    """
    Centralized instrument normalization for segments and categories.
    Used by:
      - Manual Add Instrument
      - Instrument Sync
      - Future Broker Imports
    """
    seg_raw = str(segment or "").upper().strip()
    type_raw = str(instrument_type or "").upper().strip()

    # INDICES / IDX -> segment=IND, instrument_category=INDEX
    if seg_raw == "INDICES" or type_raw == "IDX" or seg_raw == "IND":
        return "IND", "INDEX"
    # ETF -> segment=ETF, instrument_category=ETF
    elif "ETF" in seg_raw or type_raw == "ETF":
        return "ETF", "ETF"
    # FUT -> segment=FUT, instrument_category=FUTURE
    elif "FUT" in seg_raw or type_raw == "FUT":
        return "FUT", "FUTURE"
    # OPT -> segment=OPT, instrument_category=OPTION
    elif "OPT" in seg_raw or type_raw in ("OPT", "PE", "CE"):
        return "OPT", "OPTION"
    # EQ / fallback -> segment=EQ, instrument_category=STOCK
    else:
        return "EQ", "STOCK"

router = APIRouter(prefix="/instruments", tags=["instruments"])

# Input validation Regex patterns
SYMBOL_REGEX = re.compile(r"^[A-Z0-9_\-]+$")

class InstrumentCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    token: int = Field(..., gt=0)
    exchange: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    segment: str = Field(..., min_length=1, max_length=50)
    broker: Optional[str] = Field(default=None)
    instrument_category: Optional[str] = Field(default=None)

    @validator("symbol")
    def validate_symbol(cls, v):
        v_upper = v.upper().strip()
        if not SYMBOL_REGEX.match(v_upper):
            raise ValueError("Symbol must be uppercase alphanumeric (dashes and underscores allowed).")
        return v_upper

    @validator("instrument_category")
    def validate_category(cls, v):
        if v is None:
            return None
        v_upper = v.upper().strip()
        allowed = {"INDEX", "STOCK", "FUTURE", "OPTION", "ETF"}
        if v_upper not in allowed:
            raise ValueError(f"Category must be one of: {allowed}")
        return v_upper


@router.get("/search", response_model=List[Dict[str, Any]])
def search_instruments(q: str = "", limit: int = 20):
    """
    Search instruments by symbol or name case-insensitively with a limit.
    """
    logger.info(f"GET /instruments/search q='{q}', limit={limit}")
    return db_search(q, limit)


@router.get("", response_model=List[Dict[str, Any]])
def get_instruments():
    """
    Retrieves all instruments from PostgreSQL. Returns only metadata, no credentials.
    """
    logger.info("GET /instruments requested.")
    return db_get_all()


@router.post("")
def add_instrument(payload: InstrumentCreate, current_user: User = Depends(get_current_user)):
    """
    Creates/saves a new instrument in PostgreSQL after metadata and live market validation.
    """
    payload.broker = current_user.active_broker
    SEGMENT_TO_CATEGORY_MAP = {
        "EQ": "STOCK",
        "BE": "STOCK",
        "SME": "STOCK",
        "IND": "INDEX",
        "FUT": "FUTURE",
        "CE": "OPTION",
        "PE": "OPTION",
        "ETF": "ETF",
        "OPT": "OPTION",
    }
    segment_upper = payload.segment.upper().strip()
    payload.instrument_category = SEGMENT_TO_CATEGORY_MAP.get(segment_upper, "STOCK")

    logger.info(f"POST /instruments: {payload.symbol} ({payload.instrument_category}) via broker {payload.broker}")

    # Resolve active broker instance
    session = SessionLocal()
    try:
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        if not account or not account.api_key:
            raise HTTPException(
                status_code=400,
                detail="Broker credentials not configured"
            )

        api_key = decrypt_value(account.api_key)
        access_token = decrypt_value(account.access_token) if account.access_token else None

        broker = BrokerFactory.get_broker(
            current_user.active_broker,
            api_key=api_key,
            access_token=access_token
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize broker instance during validation: {e}")
        raise HTTPException(
            status_code=500,
            detail="Unable to validate instrument at this time."
        )
    finally:
        session.close()

    # STEP 1 - INSTRUMENT CORRECTNESS VALIDATION
    exchange_upper = payload.exchange.upper().strip()
    today = date.today()
    
    with _cache_lock:
        cached_date, cached_list = _instruments_cache.get(exchange_upper, (None, None))
        if cached_list is None or cached_date != today:
            logger.info(f"Fetching master instrument list from broker for exchange: {exchange_upper}")
            try:
                fetched_list = broker.get_instruments_metadata(exchange=exchange_upper)
                _instruments_cache[exchange_upper] = (today, fetched_list)
                cached_list = fetched_list
            except Exception as e:
                logger.error(f"Broker master list fetch failed for exchange {exchange_upper}: {e}")
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

    if not matched_record:
        raise HTTPException(
            status_code=400,
            detail="Instrument details do not match broker metadata. Please verify symbol, token, exchange, and segment."
        )

    # Strict check: exchange and tradingsymbol must match broker record exactly
    if str(matched_record.get("exchange") or "").upper() != exchange_upper or \
       str(matched_record.get("tradingsymbol") or "").upper() != payload.symbol.upper():
        raise HTTPException(
            status_code=400,
            detail="Instrument details do not match broker metadata. Please verify symbol, token, exchange, and segment."
        )

    # Segment and Category check
    auth_segment = str(matched_record.get("segment") or "").strip()
    auth_type = str(matched_record.get("instrument_type") or "").strip()
    derived_segment, derived_category = normalize_segment_and_category(auth_segment, auth_type)
    
    payload_segment, payload_category = normalize_segment_and_category(payload.segment, payload.instrument_category)
    if derived_segment != payload_segment or derived_category != payload_category:
        raise HTTPException(
            status_code=400,
            detail="Instrument details do not match broker metadata. Please verify symbol, token, exchange, and segment."
        )

    # Loose check: instrument name comparison (normalized whitespace/casing/trimming)
    if normalize_string(payload.name) != normalize_string(str(matched_record.get("name") or "")):
        raise HTTPException(
            status_code=400,
            detail="Instrument details do not match broker metadata. Please verify symbol, token, exchange, and segment."
        )

    # Live Market Validation using authoritative fields from matched record
    auth_exchange = matched_record.get("exchange")
    auth_symbol = matched_record.get("tradingsymbol")
    query_symbol = f"{auth_exchange}:{auth_symbol}"

    try:
        ltp_res = broker.get_ltp([query_symbol])
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

    # STEP 2 - SYMBOL UNIQUENESS VALIDATION
    existing_inst = db_get_instrument_by_symbol(payload.symbol)
    if existing_inst:
        existing_exchange = existing_inst.get("exchange") or "NSE"
        raise HTTPException(
            status_code=400,
            detail=f"{payload.symbol} already exists on exchange {existing_exchange}. Remove the existing instrument before adding another exchange version."
        )
    
    dup = db_check_duplicate(payload.symbol, payload.exchange, payload.token)
    if dup.get("token_exists"):
        raise HTTPException(
            status_code=400,
            detail="Instrument with this token already exists in database."
        )

    # STEP 3 - INSERT
    success = db_create(
        symbol=str(matched_record.get("tradingsymbol") or payload.symbol).upper().strip(),
        token=int(matched_record.get("instrument_token") or payload.token),
        exchange=str(matched_record.get("exchange") or payload.exchange).upper().strip(),
        name=str(matched_record.get("name") or payload.name).strip(),
        segment=derived_segment,
        broker=payload.broker.strip(),
        instrument_category=derived_category
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


@router.delete("/all")
def clear_all_instruments():
    """
    Deletes ALL instruments from the database and reloads the runtime cache.
    """
    logger.info("DELETE /instruments/all requested.")
    try:
        count = db_delete_all()
    except Exception as e:
        logger.error(f"Failed to clear all instruments: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear all instruments: {str(e)}")

    # Refresh runtime cache and update active subscriptions
    try:
        reload_instruments()
        from market_data.kite_client import update_subscriptions
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache or update subscriptions after clearing all: {e}")

    return {"status": "success", "message": f"All instruments cleared. {count} instrument(s) deleted."}


@router.delete("/{symbol}")
def delete_instrument(symbol: str = Path(..., min_length=1), exchange: str = None):
    """
    Deletes an instrument from PostgreSQL by symbol and exchange, and reloads cache.
    """
    if not exchange:
        raise HTTPException(status_code=400, detail="Exchange parameter is mandatory.")
    symbol_upper = symbol.upper().strip()
    exchange_upper = exchange.upper().strip()
    logger.info(f"DELETE /instruments/{symbol_upper}?exchange={exchange_upper}")
    success = db_delete(symbol_upper, exchange_upper)
    if not success:
        raise HTTPException(status_code=404, detail=f"Instrument '{symbol_upper}' on exchange '{exchange_upper}' not found.")

    # Refresh instrument cache and update active subscriptions
    try:
        reload_instruments()
        from market_data.kite_client import update_subscriptions
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache or update subscriptions: {e}")

    return {"status": "success", "message": f"Instrument '{symbol_upper}' on exchange '{exchange_upper}' deleted successfully."}


@router.post("/bulk-delete")
def bulk_delete_instruments(payload: BulkDeleteRequest):
    """
    Bulk deletes selected instruments from the database catalog.
    No subscription refresh or websocket update is performed as per architecture decision.
    """
    logger.info(f"POST /instruments/bulk-delete: processing {len(payload.instruments)} deletion targets.")
    targets = [{"symbol": item.symbol, "exchange": item.exchange} for item in payload.instruments]
    deleted_count = db_delete_bulk(targets)
    return {"status": "success", "message": f"Successfully deleted {deleted_count} instruments from the catalog."}


class SyncRequest(BaseModel):
    exchanges: List[str]
    segments: List[str]


def map_zerodha_instrument(inst: dict) -> dict:
    exch = str(inst.get("exchange") or "").upper().strip()
    seg_raw = str(inst.get("segment") or "").upper().strip()
    type_raw = str(inst.get("instrument_type") or "").upper().strip()
    symbol = str(inst.get("tradingsymbol") or "").upper().strip()
    name = str(inst.get("name") or "").strip()

    derived_segment, derived_category = normalize_segment_and_category(seg_raw, type_raw)

    return {
        "symbol": symbol,
        "token": int(inst.get("instrument_token")),
        "exchange": exch,
        "name": name,
        "segment": derived_segment,
        "broker": "ZERODHA",
                "instrument_category": derived_category
    }


@router.post("/sync")
def sync_instruments(payload: SyncRequest, current_user: User = Depends(get_current_user)):
    """
    Syncs instruments from broker master list using broker.get_instruments_metadata() filtered by exchanges and segments.
    """
    logger.info(f"POST /instruments/sync: exchanges={payload.exchanges}, segments={payload.segments}")
    
    session = SessionLocal()
    try:
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        if not account or not account.api_key:
            raise HTTPException(
                status_code=400,
                detail="Broker credentials not configured"
            )

        api_key = decrypt_value(account.api_key)
        access_token = decrypt_value(account.access_token) if account.access_token else None

        broker = BrokerFactory.get_broker(
            current_user.active_broker,
            api_key=api_key,
            access_token=access_token
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize broker instance during sync: {e}")
        raise HTTPException(
            status_code=500,
            detail="Unable to connect to broker client at this time."
        )
    finally:
        session.close()

    try:
        master_list = broker.get_instruments_metadata()
    except Exception as e:
        logger.error(f"Failed to fetch instrument master list from broker: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Broker master list fetch failed: {str(e)}"
        )

    if not master_list:
        return {"status": "success", "imported": 0, "updated": 0, "skipped": 0}

    filtered_instruments = []
    
    # Capitalize filters
    exchanges_set = {x.upper().strip() for x in payload.exchanges}
    segments_set = {s.upper().strip() for s in payload.segments}

    for inst in master_list:
        mapped = map_zerodha_instrument(inst)
        if mapped["exchange"] in exchanges_set and mapped["segment"] in segments_set:
            filtered_instruments.append(mapped)

    total_fetched = len(master_list)
    
    if filtered_instruments:
        try:
            results = db_upsert_bulk(filtered_instruments)
            imported = results["imported"]
            updated = results["updated"]
            # Reload runtime cache to ensure newly synced active instruments (if any) are indexed.
            reload_instruments()
            from market_data.kite_client import update_subscriptions
            update_subscriptions()


        except Exception as e:
            logger.error(f"Database error during bulk upsert or subscription update: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to write synced instruments or update subscriptions: {str(e)}"
            )
    else:
        imported = 0
        updated = 0

    skipped = total_fetched - (imported + updated)

    return {
        "status": "success",
        "imported": imported,
        "updated": updated,
        "skipped": skipped
    }

