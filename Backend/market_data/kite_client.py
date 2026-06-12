import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from kiteconnect import KiteTicker

# Import from local modules
from Backend.market_data.connection import create_kws
from Backend.market_data.subscriptions import get_symbol, get_tokens
from Backend.market_data.store import update_market_data
from Backend.routers.websocket import broadcast_market_update
from Backend.utils.logger import get_logger

# Set up logging
logger = get_logger(__name__)

# Keep a module-level reference to the KiteTicker instance and the main thread event loop.
_kws: Optional[KiteTicker] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# Track processed ticks for high-level health summaries
_tick_count: int = 0


async def _log_periodic_summary() -> None:
    """
    Periodically logs market data pipeline metrics every 60 seconds.
    Reads connection info from the WebSocket router manager.
    """
    global _tick_count
    from Backend.routers.websocket import manager
    while True:
        try:
            await asyncio.sleep(60)
            clients_count = len(manager.active_connections)
            logger.info(f"Processed {_tick_count:,} ticks in last minute. Connected clients: {clients_count}")
            _tick_count = 0
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic logging task: {e}")


def normalize_tick(tick: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """
    Normalizes a raw tick dict from Zerodha KiteTicker into a standardized application format.
    
    Handles varying structures between indices and equities, and provides safe defaults 
    for missing or malformed fields.
    
    Args:
        tick (Dict[str, Any]): Raw tick data from KiteTicker callback.
        symbol (str): The matching application symbol (e.g., 'RELIANCE').
        
    Returns:
        Dict[str, Any]: Normalized tick data.
    """
    # OHLC data is nested under the 'ohlc' key in Zerodha ticks
    ohlc = tick.get("ohlc", {})
    
    # Zerodha uses 'volume' for index/indices and 'volume_traded' for equities.
    # Fallback to 0 if neither exists.
    volume = tick.get("volume") or tick.get("volume_traded") or 0

    # Ensure timestamp is handled gracefully. Fallback to current local time if missing.
    tick_timestamp = tick.get("timestamp")
    if isinstance(tick_timestamp, datetime):
        timestamp_str = tick_timestamp.isoformat()
    elif isinstance(tick_timestamp, str):
        timestamp_str = tick_timestamp
    else:
        timestamp_str = datetime.now().isoformat()

    depth = tick.get("depth")
    bid_price = None
    ask_price = None
    if isinstance(depth, dict):
        buy_orders = depth.get("buy")
        if isinstance(buy_orders, list) and len(buy_orders) > 0:
            first_buy = buy_orders[0]
            if isinstance(first_buy, dict):
                bid_price = first_buy.get("price")
        
        sell_orders = depth.get("sell")
        if isinstance(sell_orders, list) and len(sell_orders) > 0:
            first_sell = sell_orders[0]
            if isinstance(first_sell, dict):
                ask_price = first_sell.get("price")

    return {
        "symbol": symbol,
        "token": tick.get("instrument_token"),
        "ltp": tick.get("last_price", 0.0),
        "change": tick.get("change", 0.0),
        "open": ohlc.get("open", 0.0),
        "high": ohlc.get("high", 0.0),
        "low": ohlc.get("low", 0.0),
        "close": ohlc.get("close", 0.0),
        "volume": volume,
        "bid": bid_price,
        "ask": ask_price,
        "timestamp": timestamp_str,
    }


def on_connect(ws: KiteTicker, response: Any) -> None:
    """
    Callback triggered on a successful connection to Zerodha KiteTicker.
    Fetches the configured tokens and registers subscription.
    """
    logger.info("KiteTicker connected successfully. Setting up subscriptions...")
    try:
        tokens = get_tokens()
        if tokens:
            # Subscribe to the numerical tokens
            ws.subscribe(tokens)
            # Set mode to FULL to receive all market depth and ticker fields (ohlc, volume, change)
            ws.set_mode(ws.MODE_FULL, tokens)
            logger.info(f"Successfully subscribed to {len(tokens)} tokens in FULL mode.")
        else:
            logger.warning("No tokens found in active subscriptions list to subscribe.")
    except Exception as e:
        logger.error(f"Failed to subscribe to instruments on connect: {e}", exc_info=True)


def on_ticks(ws: KiteTicker, ticks: List[Dict[str, Any]]) -> None:
    """
    Callback triggered when new ticks are received from the WebSocket stream.
    Normalizes ticks, updates the shared in-memory store, and schedules 
    the WebSocket broadcast on the main asyncio event loop thread-safely.
    """
    global _tick_count
    _tick_count += len(ticks)
    
    for tick in ticks:
        token = tick.get("instrument_token")
        if token is None:
            logger.warning("Received a tick with missing instrument_token.")
            continue
            
        symbol = get_symbol(token)
        if not symbol:
            continue

        try:
            normalized_data = normalize_tick(tick, symbol)
            update_market_data(symbol, normalized_data)

            # Schedule the asynchronous WebSocket broadcast on the main thread event loop thread-safely.
            # This does not block the KiteTicker callback thread.
            if _main_loop is not None and _main_loop.is_running():
                # run_coroutine_threadsafe executes without blocking the calling thread
                asyncio.run_coroutine_threadsafe(
                    broadcast_market_update(normalized_data), _main_loop
                )
            else:
                logger.warning("Main asyncio event loop is not running or unavailable for broadcast.")

        except Exception as e:
            logger.error(f"Failed to normalize and store tick for token {token} ({symbol}): {e}", exc_info=True)


def on_error(ws: KiteTicker, code: int, reason: str) -> None:
    """
    Callback triggered when the KiteTicker connection encounters an error.
    """
    logger.error(f"KiteTicker connection error. Code: {code}, Reason: {reason}")


def on_close(ws: KiteTicker, code: int, reason: str) -> None:
    """
    Callback triggered when the KiteTicker connection is closed.
    """
    logger.warning(f"KiteTicker connection closed. Code: {code}, Reason: {reason}")


def start_market_data_service(loop: asyncio.AbstractEventLoop) -> None:
    """
    Starts the background KiteTicker service.
    
    Creates a new KiteTicker instance, registers callbacks, stores a reference to 
    the main asyncio event loop, and starts the connection run loop in a background thread.
    """
    global _kws, _main_loop
    logger.info("Starting market data service...")
    
    # Store the reference to the main thread's asyncio event loop for thread-safe cross-thread calls
    _main_loop = loop
    
    # Schedule the periodic logging coroutine on the main loop
    _main_loop.create_task(_log_periodic_summary())
    
    try:
        # Create new KiteTicker using the validated connection settings
        _kws = create_kws()
        
        # Register the local event callbacks
        _kws.on_connect = on_connect
        _kws.on_ticks = on_ticks
        _kws.on_error = on_error
        _kws.on_close = on_close
        
        # Establish connection in a background thread to prevent blocking
        # FastAPI's server startup and execution loop.
        logger.info("Connecting to KiteTicker WebSocket...")
        _kws.connect(threaded=True)
        
    except Exception as e:
        logger.critical(f"Critical error starting market data service: {e}", exc_info=True)
        raise

