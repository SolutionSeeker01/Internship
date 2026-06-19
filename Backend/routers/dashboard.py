from fastapi import APIRouter
from typing import Dict, List, Any

from database.instrument_repository import get_dashboard_watchlist as db_get_dashboard_watchlist
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/watchlist", response_model=Dict[str, Any])
def get_watchlist():
    """
    Returns the instruments the dashboard should render.

    Response structure:
        {
            "indices": [...],
            "stocks":  [...],
            "view_mode": {
                "indices": "favorites" | "fallback" | "empty",
                "stocks":  "favorites" | "fallback" | "empty"
            }
        }

    Business logic is entirely backend-owned:
      - Indices: favorite indices if any exist, else top 3 active indices, else empty.
      - Stocks:  favorite stocks  if any exist, else top 10 active stocks, else empty.
    """
    logger.info("GET /dashboard/watchlist requested.")
    return db_get_dashboard_watchlist()
