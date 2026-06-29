from fastapi import APIRouter, HTTPException, Path, Body
from typing import List
from schemas.watchlist import WatchlistCreate, WatchlistUpdate, WatchlistResponse, WatchlistItemAdd, WatchlistItemResponse
from database.watchlist_repository import (
    get_all_watchlists as db_get_all,
    get_watchlist_by_id as db_get_by_id,
    create_watchlist as db_create,
    rename_watchlist as db_rename,
    delete_watchlist as db_delete,
    get_watchlist_items as db_get_items,
    add_instrument_to_watchlist as db_add_item,
    remove_instrument_from_watchlist as db_remove_item,
    get_watchlist_items_count as db_get_items_count,
    check_instrument_in_watchlist as db_check_item_exists
)
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlists", tags=["Watchlists"])

@router.get("", response_model=List[WatchlistResponse])
def get_watchlists():
    """
    List all watchlists.
    """
    logger.info("GET /watchlists requested.")
    return db_get_all()

@router.post("", response_model=WatchlistResponse)
def create_watchlist(payload: WatchlistCreate):
    """
    Create a new watchlist.
    """
    logger.info(f"POST /watchlists name='{payload.name}'")
    watchlist = db_create(payload.name)
    if not watchlist:
        raise HTTPException(status_code=400, detail="Failed to create watchlist. Name may already exist.")
    return watchlist

@router.patch("/{id}", response_model=WatchlistResponse)
def rename_watchlist(id: int = Path(..., gt=0), payload: WatchlistUpdate = Body(...)):
    """
    Rename an existing watchlist.
    """
    logger.info(f"PATCH /watchlists/{id} name='{payload.name}'")
    watchlist = db_get_by_id(id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    
    updated = db_rename(id, payload.name)
    if not updated:
        raise HTTPException(status_code=400, detail="Failed to rename watchlist. Name may already exist.")
    return updated

@router.delete("/{id}")
def delete_watchlist(id: int = Path(..., gt=0)):
    """
    Delete a watchlist.
    """
    logger.info(f"DELETE /watchlists/{id}")
    watchlist = db_get_by_id(id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    
    success = db_delete(id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete watchlist.")
    return {"status": "success", "message": "Watchlist deleted successfully."}


@router.get("/{id}/items", response_model=List[WatchlistItemResponse])
def get_watchlist_items(id: int = Path(..., gt=0)):
    """
    Fetch all items belonging to a watchlist.
    """
    logger.info(f"GET /watchlists/{id}/items")
    watchlist = db_get_by_id(id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    return db_get_items(id)


@router.post("/{id}/items")
def add_watchlist_item(id: int = Path(..., gt=0), payload: WatchlistItemAdd = Body(...)):
    """
    Add an instrument to a watchlist (limit 100, no duplicates).
    """
    logger.info(f"POST /watchlists/{id}/items instrument_id={payload.instrument_id}")
    watchlist = db_get_by_id(id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
    
    # 1. Enforce max limit of 100
    current_count = db_get_items_count(id)
    if current_count >= 100:
        raise HTTPException(
            status_code=400,
            detail="Watchlist already contains the maximum number of instruments (100)."
        )
    
    # 2. Prevent duplicate entries
    exists = db_check_item_exists(id, payload.instrument_id)
    if exists:
        raise HTTPException(
            status_code=400,
            detail="Instrument already exists in this watchlist."
        )
        
    success = db_add_item(id, payload.instrument_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to add instrument to watchlist.")
    
    # Refresh ticker subscriptions dynamically
    try:
        from market_data.subscriptions import reload_instruments
        from market_data.kite_client import update_subscriptions
        reload_instruments()
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to refresh subscriptions on item addition: {e}")
        
    return {"status": "success", "message": "Instrument added to watchlist successfully."}


@router.delete("/{id}/items/{instrument_id}")
def remove_watchlist_item(id: int = Path(..., gt=0), instrument_id: int = Path(..., gt=0)):
    """
    Remove an instrument from a watchlist.
    """
    logger.info(f"DELETE /watchlists/{id}/items/{instrument_id}")
    watchlist = db_get_by_id(id)
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found.")
        
    success = db_remove_item(id, instrument_id)
    if not success:
        raise HTTPException(status_code=404, detail="Instrument not found in this watchlist.")
        
    # Refresh ticker subscriptions dynamically
    try:
        from market_data.subscriptions import reload_instruments
        from market_data.kite_client import update_subscriptions
        reload_instruments()
        update_subscriptions()
    except Exception as e:
        logger.warning(f"Failed to refresh subscriptions on item deletion: {e}")
        
    return {"status": "success", "message": "Instrument removed from watchlist successfully."}

