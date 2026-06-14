from fastapi import APIRouter, HTTPException
from Backend.database.repository import get_candles
from Backend.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/candles", tags=["candles"])


@router.get("/{symbol}")
def get_historical_candles(symbol: str, limit: int = 100):
    """
    REST endpoint to retrieve historical 1-minute candles for a specific symbol.
    
    Args:
        symbol (str): The trading asset symbol (e.g. RELIANCE, NIFTY50).
        limit (int): Number of candles to return (between 1 and 1000). Defaults to 100.
        
    Returns:
        List[Dict[str, Any]]: A chronological list of candles (oldest to newest).
    """
    symbol_upper = symbol.upper()

    # Reject invalid limits (<1 or >1000)
    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=400, 
            detail="Invalid limit parameter. Limit must be between 1 and 1000."
        )

    try:
        candles = get_candles(symbol_upper, limit)
        return candles
    except Exception as e:
        # Prevent leaking raw database driver exceptions to the client
        logger.error(f"Unexpected error in GET /candles/{symbol_upper}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail="Failed to retrieve historical candlestick data."
        )
