from fastapi import APIRouter, HTTPException, Path, Body
from pydantic import BaseModel, Field, validator
import re
from typing import List, Dict, Any

from database.instrument_repository import (
    get_all_instruments as db_get_all,
    create_instrument as db_create,
    delete_instrument as db_delete,
    toggle_favorite as db_toggle_favorite,
    get_favorite_instruments as db_get_favorites
)
from market_data.subscriptions import reload_instruments
from utils.logger import get_logger

logger = get_logger(__name__)

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
        if v_upper not in ("INDEX", "STOCK"):
            raise ValueError("Category must be either 'INDEX' or 'STOCK'.")
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
    Creates/saves a new instrument in PostgreSQL and reloads the active subscriptions cache.
    """
    logger.info(f"POST /instruments: {payload.symbol} ({payload.instrument_category})")
    success = db_create(
        symbol=payload.symbol,
        token=payload.token,
        exchange=payload.exchange,
        name=payload.name,
        segment=payload.segment,
        broker=payload.broker,
        instrument_category=payload.instrument_category
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to write instrument to database.")

    # Refresh instrument cache
    try:
        reload_instruments()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache (it might be empty of active items): {e}")

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

    # Refresh instrument cache
    try:
        reload_instruments()
    except Exception as e:
        logger.warning(f"Failed to reload instrument cache (it might be empty of active items): {e}")

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
