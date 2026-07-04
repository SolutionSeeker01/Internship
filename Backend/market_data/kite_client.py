import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from kiteconnect import KiteTicker

# Import from local modules
from market_data.connection import create_kws, create_kite_client, reset_connection_state
from market_data.subscriptions import get_symbol, get_tokens, get_instrument_metadata
from market_data.store import update_market_data
from routers.websocket import broadcast_market_update
from utils.logger import get_logger
from schemas.ticks import NormalizedTick
import threading

# Set up logging
logger = get_logger(__name__)

# Keep a module-level reference to the KiteTicker instance and the main thread event loop.
_kws: Optional[KiteTicker] = None
_main_loop: Optional[asyncio.AbstractEventLoop] = None

# Active broker adapter singleton reference managed by Phase 3B orchestrator
from services.brokers.base import BaseBroker
from services.brokers.factory import BrokerFactory
_active_broker: Optional[BaseBroker] = None

# Track processed ticks for high-level health summaries
_tick_count: int = 0

# Keep track of currently subscribed tokens
_subscribed_tokens = set()

# State variables for service controls
_market_service_running: bool = False
_market_service_lock = threading.RLock()

# Track periodic logging task reference to prevent duplicate leak tasks
_summary_task: Optional[asyncio.Task] = None


async def _log_periodic_summary() -> None:
    """
    Periodically logs market data pipeline metrics every 60 seconds.
    Reads connection info from the WebSocket router manager.
    """
    global _tick_count
    from routers.websocket import manager
    while True:
        try:
            await asyncio.sleep(60)
            clients_count = len(manager.active_connections)
            logger.debug(f"Processed {_tick_count:,} ticks in last minute. Connected clients: {clients_count}")
            _tick_count = 0
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in periodic logging task: {e}")


def normalize_tick(tick: Dict[str, Any], symbol: str, exchange: str) -> Dict[str, Any]:
    """
    Normalizes a raw tick dict from Zerodha KiteTicker into a standardized application format.
    
    Handles varying structures between indices and equities, and provides safe defaults 
    for missing or malformed fields.
    
    Args:
        tick (Dict[str, Any]): Raw tick data from KiteTicker callback.
        symbol (str): The matching application symbol (e.g., 'RELIANCE').
        exchange (str): The exchange the tick belongs to (e.g., 'NSE').
        
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
        ts = tick_timestamp
    elif isinstance(tick_timestamp, str):
        try:
            ts = datetime.fromisoformat(tick_timestamp)
        except Exception:
            ts = datetime.now()
    else:
        ts = datetime.now()

    depth = tick.get("depth")
    bid_price = None
    ask_price = None
    if isinstance(depth, dict):
        buy_orders = depth.get("buy")
        if isinstance(buy_orders, list) and len(buy_orders) > 0:
            first_buy = buy_orders[0]
            if isinstance(first_buy, dict):
                price = first_buy.get("price")
                if price and price != 0:  # Prefer None over fake zero values
                    bid_price = price
        
        sell_orders = depth.get("sell")
        if isinstance(sell_orders, list) and len(sell_orders) > 0:
            first_sell = sell_orders[0]
            if isinstance(first_sell, dict):
                price = first_sell.get("price")
                if price and price != 0:  # Prefer None over fake zero values
                    ask_price = price

    normalized = NormalizedTick(
        key=f"{exchange}:{symbol}",
        symbol=symbol,
        exchange=exchange,
        ltp=float(tick.get("last_price", 0.0)),
        change=float(tick.get("change", 0.0)),
        open=float(ohlc.get("open", 0.0)),
        high=float(ohlc.get("high", 0.0)),
        low=float(ohlc.get("low", 0.0)),
        close=float(ohlc.get("close", 0.0)),
        volume=int(volume),
        bid=bid_price,
        ask=ask_price,
        timestamp=ts
    )
    return normalized.model_dump()


def on_tick_received(normalized_data: Dict[str, Any]) -> None:
    """
    Callback triggered by the active broker feed adapter when a new normalized tick is received.
    Updates the shared store and schedules the async WebSocket broadcast.
    """
    global _tick_count
    _tick_count += 1
    
    key = normalized_data["key"]
    update_market_data(key, normalized_data)
    
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            broadcast_market_update(normalized_data), _main_loop
        )


# TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
def on_connect(ws: KiteTicker, response: Any) -> None:
    """
    Callback triggered on a successful connection to Zerodha KiteTicker.
    Fetches the configured tokens and registers subscription.
    """
    global _subscribed_tokens
    logger.info("KiteTicker connected successfully. Setting up subscriptions...")
    try:
        tokens = get_tokens()
        if tokens:
            if len(tokens) > 4000:
                logger.critical(f"REFUSING SUBSCRIPTION UPDATE: Attempted to subscribe to {len(tokens)} tokens, which exceeds the limit of 4000.")
                _subscribed_tokens = set()
                return

            # Subscribe to the numerical tokens
            ws.subscribe(tokens)
            # Set mode to FULL to receive all market depth and ticker fields (ohlc, volume, change)
            ws.set_mode(ws.MODE_FULL, tokens)
            logger.info(f"Successfully subscribed to {len(tokens)} tokens in FULL mode.")
            _subscribed_tokens = set(tokens)
        else:
            logger.warning("No tokens found in active subscriptions list to subscribe.")
            _subscribed_tokens = set()
    except Exception as e:
        logger.error(f"Failed to subscribe to instruments on connect: {e}", exc_info=True)
        _subscribed_tokens = set()


# TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
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
            
        meta = get_instrument_metadata(token)
        if not meta:
            continue
        symbol = meta["symbol"]
        exchange = meta["exchange"]
 
        try:
            normalized_data = normalize_tick(tick, symbol, exchange)
            key = normalized_data["key"]
            update_market_data(key, normalized_data)

            # Schedule the asynchronous WebSocket broadcast on the main thread event loop thread-safely.
            # This does not block the KiteTicker callback thread.
            if _main_loop is not None and _main_loop.is_running():
                # run_coroutine_threadsafe executes without blocking the calling thread
                asyncio.run_coroutine_threadsafe(
                    broadcast_market_update(normalized_data), _main_loop
                )
                logger.debug(f"Broadcast tick: {symbol}")
            else:
                logger.warning("Main asyncio event loop is not running or unavailable for broadcast.")



        except Exception as e:
            logger.error(f"Failed to normalize and store tick for token {token} ({symbol}): {e}", exc_info=True)


# TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
def on_error(ws: KiteTicker, code: int, reason: str) -> None:
    """
    Callback triggered when the KiteTicker connection encounters an error.
    Handles running state reset on critical/permanent termination errors.
    """
    logger.error(f"KiteTicker connection error. Code: {code}, Reason: {reason}")


# TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
def on_close(ws: KiteTicker, code: int, reason: str) -> None:
    """
    Callback triggered when the KiteTicker connection is closed.
    Acquires the lock and toggles running state flags to prevent stale state references
    ONLY if the closing websocket matches the active instance.
    Resets the centralized KiteConnect state.
    """
    global _market_service_running, _kws, _summary_task
    logger.warning(f"KiteTicker connection closed. Code: {code}, Reason: {reason}")
    with _market_service_lock:
        if ws is _kws:
            _market_service_running = False
            _kws = None
            
            # Cancel periodic logging task if running to prevent memory leaks on unexpected disconnections
            if _summary_task is not None:
                if not _summary_task.done():
                    _summary_task.cancel()
                _summary_task = None

            try:
                reset_connection_state()
            except Exception:
                logger.exception(
                    "Failed to reset centralized KiteConnect state during websocket shutdown."
                )
        else:
            logger.info("Ignoring websocket close event from stale KiteTicker instance.")


def is_market_service_running() -> bool:
    """
    Returns current running state of the market data service.
    """
    global _active_broker, _market_service_running
    with _market_service_lock:
        if _active_broker is not None:
            return _active_broker.is_feed_running()
        return _market_service_running


def get_active_broker_client() -> Optional[BaseBroker]:
    """
    Returns the active singleton broker adapter instance managed by the market data service.
    """
    global _active_broker
    return _active_broker


def start_market_data_service(loop: asyncio.AbstractEventLoop, api_key: str, access_token: str) -> None:
    """
    Starts the background KiteTicker service dynamically.
    """
    global _main_loop, _market_service_running, _summary_task, _active_broker
    with _market_service_lock:
        if is_market_service_running():
            logger.warning("Market data service is already running. Ignoring start request.")
            return

        logger.info("Starting market data service dynamically (delegated to Active Broker)...")
        
        # Store the reference to the main thread's asyncio event loop for thread-safe cross-thread calls
        _main_loop = loop
        
        # Schedule the periodic logging coroutine on the main loop if not already running or done
        if _summary_task is None or _summary_task.done():
            _summary_task = _main_loop.create_task(_log_periodic_summary())
        
        try:
            # Phase 3B Broker Abstraction Delegation
            if _active_broker is None:
                _active_broker = BrokerFactory.get_broker(
                    "zerodha",
                    api_key=api_key,
                    access_token=access_token
                )
            else:
                # Update credentials on the existing instance if they changed
                _active_broker.api_key = api_key
                _active_broker.access_token = access_token

            tokens = list(get_tokens())
            _active_broker.start_feed(
                loop=loop,
                subscription_tokens=tokens,
                on_tick_callback=on_tick_received
            )
            _market_service_running = True
            return
        except Exception as e:
            logger.exception("Failed to start market data feed via active broker adapter.", exc_info=True)
            _market_service_running = False
            _active_broker = None
            if _summary_task is not None and not _summary_task.done():
                _summary_task.cancel()
            _summary_task = None
            raise

        # TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
        # Legacy Zerodha-specific path (remains here but bypassed by active broker delegation above)
        # global _kws, _subscribed_tokens
        # try:
        #     # Dynamically initialize centralized KiteConnect client first
        #     create_kite_client(api_key, access_token)
        #     # Create new KiteTicker using the supplied connection credentials
        #     _kws = create_kws(api_key, access_token)
        #     # Register the local event callbacks
        #     _kws.on_connect = on_connect
        #     _kws.on_ticks = on_ticks
        #     _kws.on_error = on_error
        #     _kws.on_close = on_close
        #     # Establish connection in a background thread to prevent blocking
        #     logger.info("Connecting to KiteTicker WebSocket...")
        #     _kws.connect(threaded=True)
        #     _market_service_running = True
        # except Exception as e:
        #     logger.critical(f"Critical error starting market data service dynamically: {e}", exc_info=True)
        #     _market_service_running = False
        #     _kws = None
        #     _main_loop = None
        #     _subscribed_tokens.clear()
        #     if _summary_task is not None and not _summary_task.done():
        #         _summary_task.cancel()
        #     _summary_task = None
        #     try:
        #         reset_connection_state()
        #     except Exception:
        #         pass
        #     raise


def stop_market_data_service() -> None:
    """
    Stops the background KiteTicker service and resets connection structures.
    """
    global _active_broker, _market_service_running, _summary_task
    with _market_service_lock:
        logger.info("Stopping market data service (delegated to Active Broker)...")
        
        if _active_broker is not None:
            try:
                _active_broker.stop_feed()
            except Exception as e:
                logger.error(f"Error stopping active broker feed: {e}")
            
        # Cancel periodic summary logging task if running to prevent memory leaks
        if _summary_task is not None:
            if not _summary_task.done():
                _summary_task.cancel()
            _summary_task = None
        
        _market_service_running = False
        logger.info("Market data service successfully stopped.")
        return

        # TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
        # global _kws, _subscribed_tokens
        # if not _market_service_running:
        #     logger.info("Market data service is not running. Ignoring stop request.")
        #     return
        # logger.info("Stopping market data service...")
        # try:
        #     if _kws is not None:
        #         _kws.close()
        # except Exception as e:
        #     logger.error(f"Error closing KiteTicker websocket connection: {e}")
        # _kws = None
        # _subscribed_tokens.clear()
        # if _summary_task is not None:
        #     if not _summary_task.done():
        #         _summary_task.cancel()
        #     _summary_task = None
        # reset_connection_state()
        # _market_service_running = False
        # logger.info("Market data service successfully stopped.")


def restart_market_data_service(loop: asyncio.AbstractEventLoop, api_key: str, access_token: str) -> None:
    """
    Stops and restarts the background KiteTicker service dynamically.
    """
    with _market_service_lock:
        stop_market_data_service()
        start_market_data_service(loop, api_key, access_token)


def update_subscriptions() -> None:
    """
    Updates the active KiteTicker subscriptions based on the latest cache.
    Automatically unsubscribes from deleted tokens and subscribes to new tokens.
    """
    global _active_broker
    if _active_broker is not None and _active_broker.is_feed_running():
        try:
            current_tokens = list(get_tokens())
            _active_broker.update_subscriptions(current_tokens)
        except Exception as e:
            logger.error(f"Failed to update active broker subscriptions: {e}")
        return

    # TODO: DEPRECATED AFTER PHASE 3B VERIFICATION
    # global _kws, _subscribed_tokens
    # if _kws is not None and _kws.is_connected():
    #     try:
    #         current_tokens = set(get_tokens())
    #         if len(current_tokens) > 4000:
    #             logger.critical(f"REFUSING SUBSCRIPTION UPDATE: Attempted to subscribe to {len(current_tokens)} tokens, which exceeds the limit of 4000.")
    #             return
    #         to_unsubscribe = _subscribed_tokens - current_tokens
    #         if to_unsubscribe:
    #             _kws.unsubscribe(list(to_unsubscribe))
    #             logger.info(f"KiteTicker unsubscribed from {len(to_unsubscribe)} tokens: {list(to_unsubscribe)}")
    #         if current_tokens:
    #             _kws.subscribe(list(current_tokens))
    #             _kws.set_mode(_kws.MODE_FULL, list(current_tokens))
    #             logger.info(f"KiteTicker successfully updated subscriptions to {len(current_tokens)} tokens in FULL mode.")
    #         _subscribed_tokens = current_tokens
    #     except Exception as e:
    #         logger.error(f"Failed to update KiteTicker subscriptions dynamically: {e}")
    # else:
    #     logger.warning("KiteTicker is not connected. Subscriptions will load on connect.")

