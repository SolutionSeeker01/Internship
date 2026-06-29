from fastapi import APIRouter, Query
from typing import Dict, List, Any, Optional

from database.instrument_repository import get_dashboard_watchlist as db_get_dashboard_watchlist
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/watchlist", response_model=Dict[str, Any])
def get_watchlist(watchlist_id: Optional[int] = Query(None)):
    """
    Returns the instruments the dashboard should render.
    """
    logger.info(f"GET /dashboard/watchlist requested. watchlist_id={watchlist_id}")
    return db_get_dashboard_watchlist(watchlist_id)

