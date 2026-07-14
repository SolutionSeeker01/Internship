from datetime import datetime, timedelta
import requests
from fastapi import APIRouter, HTTPException, Query, Depends
from market_data.subscriptions import get_all_instruments
from utils.logger import get_logger
from dependencies.auth import get_current_user
from database.db import SessionLocal
from models.broker_account import BrokerAccount
from security.encryption import decrypt_value
from services.brokers.factory import BrokerFactory

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
    exchange: str = Query(default=None),
    interval: str = Query(default="minute"),
    limit: int = 100,
    current_user = Depends(get_current_user)
):
    """
    Retrieves historical candles directly from the Zerodha Historical API.
    
    Args:
        symbol (str): The trading asset symbol (e.g. RELIANCE, NIFTY50).
        exchange (str): The exchange metadata (e.g. NSE, BSE).
        interval (str): Time interval (minute, 3minute, 5minute, 10minute, 15minute, 30minute, 60minute, day).
        limit (int): Number of candles to return. Defaults to 100.
        
    Returns:
        List[Dict[str, Any]]: A chronological list of candles matching V1 JSON structure.
    """
    symbol_upper = symbol.upper().strip()
    exch_upper = exchange.upper().strip() if exchange else None

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
        instruments = get_all_instruments()
        meta = None
        for inst in instruments:
            if inst["symbol"].upper() == symbol_upper:
                if exch_upper is None or inst["exchange"].upper() == exch_upper:
                    meta = inst
                    break
        if not meta:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol '{symbol_upper}' not found in master catalog registry."
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

    # Log query target in the specified formatted layout
    resolved_exchange = meta["exchange"] if meta else (exchange or "NSE")
    logger.info(
        f"Loading candles:\n"
        f"    Symbol   = {symbol_upper}\n"
        f"    Exchange = {resolved_exchange}\n"
        f"    Interval = {interval}"
    )

    # 4. Determine lookback periods for from_date/to_date boundaries
    to_date = datetime.now()
    if interval == "minute":
        # Safe lookback to handle weekends and after-hours data
        from_date = to_date - timedelta(days=7)
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

    # 5. Retrieve dynamic user credentials from database based on active session broker
    session = SessionLocal()
    try:
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == current_user.id
        ).first()

        if not account or not account.api_key or not account.access_token:
            raise HTTPException(
                status_code=400,
                detail="Broker account or active session credentials not found. Please connect your broker account first."
            )

        try:
            api_key = decrypt_value(account.api_key)
            access_token = decrypt_value(account.access_token)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Failed to decrypt stored broker credentials."
            )
    finally:
        session.close()

    # 6. Resolve broker adapter and fetch historical candles
    try:
        broker = BrokerFactory.get_broker(
            current_user.active_broker,
            api_key=api_key,
            access_token=access_token
        )
        historical_candles = broker.get_historical_candles(
            instrument_token=instrument_token,
            interval=interval,
            from_date=from_date,
            to_date=to_date
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error fetching historical candles via adapter: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve historical data from broker."
        )

    # 7. Slice to limit (chronologically oldest to newest, take last N elements)
    recent_candles = historical_candles[-limit:] if historical_candles else []

    # 8. Re-format response into EXACT same JSON schema structure returned previously
    formatted_candles = []
    for candle in recent_candles:
        date_val = candle.candle_start
        date_str = date_val.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(date_val, 'strftime') else str(date_val)

        formatted_candles.append({
            "candle_start": date_str,
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": int(candle.volume)
        })

    return formatted_candles
