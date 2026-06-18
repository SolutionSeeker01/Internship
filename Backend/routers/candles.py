from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from market_data.subscriptions import get_all_instruments
from market_data.connection import get_kite
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/candles", tags=["candles"])

# Set of supported/validated historical intervals
VALID_INTERVALS = {
    "minute",
    "3minute",
    "5minute",
    "10minute",
    "15minute",
    "30minute",
    "60minute",
    "day"
}


@router.get("/{symbol}")
def get_historical_candles(
    symbol: str,
    interval: str = Query(default="minute"),
    limit: int = 100
):
    """
    Retrieves historical candles directly from the Zerodha Historical API.
    
    Args:
        symbol (str): The trading asset symbol (e.g. RELIANCE, NIFTY50).
        interval (str): Time interval (minute, 3minute, 5minute, 10minute, 15minute, 30minute, 60minute, day).
        limit (int): Number of candles to return. Defaults to 100.
        
    Returns:
        List[Dict[str, Any]]: A chronological list of candles matching V1 JSON structure.
    """
    symbol_upper = symbol.upper()

    # 1. Validate interval parameter
    if interval not in VALID_INTERVALS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval parameter '{interval}'. Must be one of: {', '.join(VALID_INTERVALS)}"
        )

    # 2. Validate limit parameter
    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=400,
            detail="Invalid limit parameter. Limit must be between 1 and 1000."
        )

    # 3. Resolve symbol to numerical instrument token using subscriptions cache
    try:
        active_instruments = get_all_instruments()
        meta = next((inst for inst in active_instruments if inst["symbol"].upper() == symbol_upper), None)
        if not meta:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol '{symbol_upper}' not found in active instruments registry."
            )
        instrument_token = meta["token"]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resolving symbol '{symbol_upper}' to token: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to resolve symbol metadata."
        )

    # Log query target
    logger.info(f"Fetching historical candles: {symbol_upper} interval={interval}")

    # 4. Determine lookback periods for from_date/to_date boundaries
    to_date = datetime.now()
    if interval == "minute":
        # Safe lookback to handle weekends and after-hours data
        from_date = to_date - timedelta(days=2)
    elif interval == "3minute":
        from_date = to_date - timedelta(days=3)
    elif interval == "5minute":
        from_date = to_date - timedelta(days=6)
    elif interval == "10minute":
        from_date = to_date - timedelta(days=10)
    elif interval == "15minute":
        from_date = to_date - timedelta(days=20)
    elif interval == "30minute":
        from_date = to_date - timedelta(days=35)
    elif interval == "60minute":
        from_date = to_date - timedelta(days=65)
    elif interval == "day":
        from_date = to_date - timedelta(days=180)
    else:
        from_date = to_date - timedelta(days=2)

    # 5. Retrieve centralized authenticated KiteConnect session
    try:
        kite = get_kite()

        # 6. Fetch historical candles from Zerodha
        historical_data = kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval
        )

        # 7. Slice to limit (chronologically oldest to newest, take last N elements)
        recent_candles = historical_data[-limit:] if historical_data else []

        # 8. Re-format response into EXACT same JSON schema structure returned previously
        formatted_candles = []
        for candle in recent_candles:
            # Format candle date to standard YYYY-MM-DDTHH:MM:SS string
            date_val = candle.get("date")
            date_str = date_val.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(date_val, 'strftime') else str(date_val)

            formatted_candles.append({
                "candle_start": date_str,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": int(candle["volume"])
            })

        return formatted_candles

    except Exception as e:
        logger.error(f"Failed to fetch historical candles from Zerodha for {symbol_upper}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve historical candlestick data from broker."
        )
