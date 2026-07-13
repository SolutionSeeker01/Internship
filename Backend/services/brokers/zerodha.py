from services.brokers.base import BaseBroker
from typing import Dict, Any, List, Optional
from datetime import datetime
from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException
import requests
from schemas.candles import HistoricalCandle
from utils.logger import get_logger
from exceptions import ValidationException, BrokerAdapterException

logger = get_logger(__name__)

class ZerodhaBroker(BaseBroker):
    """
    Zerodha provider implementation.
    """
    LOGIN_URL = "https://kite.zerodha.com/connect/login"

    def __init__(self, api_key: str, api_secret: str = None, access_token: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self._intentional_shutdown = False

    def get_login_url(self, state: str) -> str:
        """
        Constructs the Zerodha Kite Connect login redirect URL.
        """
        # Validate presence
        if not self.api_key:
            raise ValidationException("API key not configured")

        return (
            f"{self.LOGIN_URL}"
            f"?api_key={self.api_key}"
            f"&v=3"
            f"&state={state}"
        )

    def handle_callback(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles the Zerodha callback, exchanging request_token for long-lived session access token.
        """
        request_token = params.get("request_token")
        if not request_token:
            raise ValidationException("request_token is required in params")
            
        if not self.api_key or not self.api_secret:
            raise ValidationException("API credentials (api_key/api_secret) are not configured on this provider.")

        try:
            kite = KiteConnect(api_key=self.api_key)
            session_data = kite.generate_session(
                request_token=request_token,
                api_secret=self.api_secret
            )
            return {
                "access_token": session_data["access_token"],
                "broker_username": session_data["user_name"],
                "broker_user_id": session_data.get("user_id"),
                "refresh_token": None
            }
        except (KiteException, requests.exceptions.RequestException) as e:
            raise BrokerAdapterException("Zerodha authentication failed. Please check your credentials and request token.", original_exception=e)

    def is_session_valid(self, api_key: str, access_token: str) -> bool:
        """
        Unimplemented session validator.
        """
        raise NotImplementedError("is_session_valid is not implemented in ZerodhaBroker.")

    def get_historical_candles(
        self,
        instrument_token: int,
        interval: str,
        from_date: datetime,
        to_date: datetime
    ) -> List[HistoricalCandle]:
        """
        Retrieves historical candlestick data for the specified instrument token.
        """
        if not self.api_key or not self.access_token:
            raise ValidationException("API credentials (api_key/access_token) are not configured on this provider.")

        try:
            kite = KiteConnect(api_key=self.api_key, timeout=30)
            kite.set_access_token(self.access_token)
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Failed to initialize Kite client session: {e}")
            raise BrokerAdapterException("Failed to initialize connection to broker.", original_exception=e)

        # Fetch historical candles from Zerodha with retry logic
        historical_data = None
        try:
            historical_data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Timeout/Connection error fetching historical data for token {instrument_token} on first attempt: {e}. Retrying once...")
            try:
                historical_data = kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e2:
                logger.error(f"Timeout/Connection error fetching historical data for token {instrument_token} on retry: {e2}")
                raise BrokerAdapterException("Timeout retrieving historical data from broker.", original_exception=e2)
            except (KiteException, requests.exceptions.RequestException) as e2:
                logger.error(f"Unexpected error fetching historical data for token {instrument_token} on retry: {e2}")
                raise BrokerAdapterException("Unexpected broker error during retry.", original_exception=e2)
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Failed to fetch historical candles from Zerodha for token {instrument_token}: {e}")
            raise BrokerAdapterException("Failed to retrieve historical candlestick data from broker.", original_exception=e)

        # Normalize responses
        normalized_candles = []
        if historical_data:
            for candle in historical_data:
                normalized_candles.append(HistoricalCandle(
                    candle_start=candle["date"],
                    open=float(candle["open"]),
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    close=float(candle["close"]),
                    volume=int(candle["volume"])
                ))
        return normalized_candles

    def start_feed(self, loop: Any, subscription_tokens: List[int], on_tick_callback: Any) -> None:
        """
        Spawns the background WebSocket client feed for this broker.
        """
        from kiteconnect import KiteTicker

        if not self.api_key or not self.access_token:
            raise ValidationException("API credentials (api_key/access_token) are required for starting feed.")

        if self.is_feed_running():
            logger.warning("Zerodha feed is already running.")
            return

        self._on_tick_callback = on_tick_callback
        self._subscribed_tokens = set(subscription_tokens)

        try:
            self._kws = KiteTicker(api_key=self.api_key, access_token=self.access_token)

            # Register callbacks
            self._kws.on_connect = self._on_ticker_connect
            self._kws.on_ticks = self._on_ticker_ticks
            self._kws.on_error = self._on_ticker_error
            self._kws.on_close = self._on_ticker_close

            logger.info("Connecting to Zerodha KiteTicker WebSocket...")
            self._kws.connect(threaded=True)
        except (KiteException, requests.exceptions.RequestException, ConnectionError) as e:
            logger.critical(f"Failed to start Zerodha KiteTicker: {e}", exc_info=True)
            self._kws = None
            self._on_tick_callback = None
            raise BrokerAdapterException("Failed to start Zerodha KiteTicker feed.", original_exception=e)

    def stop_feed(self) -> None:
        """
        Terminates the WebSocket client feed connection and resets connection structures.
        """
        self._intentional_shutdown = True
        if hasattr(self, "_kws") and self._kws is not None:
            try:
                self._kws.close()
            except Exception as e:
                logger.error(f"Error closing Zerodha KiteTicker: {e}")
            self._kws = None
        self._on_tick_callback = None
        logger.info("Zerodha KiteTicker successfully stopped.")

    def update_subscriptions(self, subscription_tokens: List[int]) -> None:
        """
        Dynamically updates active ticker subscriptions.
        """
        if hasattr(self, "_kws") and self._kws is not None and self._kws.is_connected():
            try:
                current_tokens = set(subscription_tokens)
                if len(current_tokens) > 4000:
                    logger.critical(f"REFUSING SUBSCRIPTION UPDATE: Attempted to subscribe to {len(current_tokens)} tokens.")
                    return

                to_unsubscribe = self._subscribed_tokens - current_tokens
                if to_unsubscribe:
                    self._kws.unsubscribe(list(to_unsubscribe))
                    logger.info(f"Zerodha ticker unsubscribed from: {list(to_unsubscribe)}")

                if current_tokens:
                    self._kws.subscribe(list(current_tokens))
                    self._kws.set_mode(self._kws.MODE_FULL, list(current_tokens))
                    logger.info(f"Zerodha ticker subscribed to {len(current_tokens)} tokens in FULL mode.")

                self._subscribed_tokens = current_tokens
            except Exception as e:
                logger.error(f"Failed to update Zerodha subscriptions: {e}")
        else:
            logger.warning("Zerodha ticker is not connected. Subscriptions will load on connect.")

    def is_feed_running(self) -> bool:
        """
        Returns True if the WebSocket client feed is active and running.
        """
        return hasattr(self, "_kws") and self._kws is not None and self._kws.is_connected()

    # Low-level Zerodha ticker callbacks
    def _on_ticker_connect(self, ws, response):
        logger.info("Successfully connected to Zerodha KiteTicker.")
        tokens = list(self._subscribed_tokens)
        if tokens:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            logger.info(f"Successfully subscribed to {len(tokens)} tokens in FULL mode on connect.")

    def _on_ticker_ticks(self, ws, ticks):
        if not hasattr(self, "_on_tick_callback") or not self._on_tick_callback:
            return

        for tick in ticks:
            token = tick.get("instrument_token")
            if token is None:
                continue

            from market_data.subscriptions import get_instrument_metadata
            meta = get_instrument_metadata(token)
            if not meta:
                continue
            symbol = meta["symbol"]
            exchange = meta["exchange"]

            try:
                from market_data.kite_client import normalize_tick
                normalized_data = normalize_tick(tick, symbol, exchange)
                self._on_tick_callback(normalized_data)
            except Exception as e:
                logger.error(f"Error normalizing Zerodha tick: {e}", exc_info=True)

    def _on_ticker_error(self, ws, code, reason):
        if getattr(self, "_intentional_shutdown", False):
            logger.info(f"Zerodha Ticker connection error ignored during intentional shutdown: {code} - {reason}")
        else:
            logger.error(f"Zerodha Ticker connection error: {code} - {reason}")

    def _on_ticker_close(self, ws, code, reason):
        if getattr(self, "_intentional_shutdown", False):
            logger.info(f"Zerodha Ticker connection closed gracefully (Intentional): {code} - {reason}")
        else:
            logger.warning(f"Zerodha Ticker connection closed: {code} - {reason}")

    def get_instruments_metadata(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches the master instrument list from Zerodha.
        """
        if not self.api_key:
            raise ValidationException("API key is not configured on this provider.")

        try:
            kite = KiteConnect(api_key=self.api_key, timeout=30)
            if self.access_token:
                kite.set_access_token(self.access_token)
            if exchange:
                return kite.instruments(exchange=exchange)
            return kite.instruments()
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Failed to fetch Zerodha instruments metadata: {e}")
            raise BrokerAdapterException("Failed to fetch Zerodha instruments metadata.", original_exception=e)

    def get_ltp(self, query_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Queries the last traded price for the given symbols from Zerodha.
        """
        if not self.api_key:
            raise ValidationException("API key is not configured on this provider.")

        try:
            kite = KiteConnect(api_key=self.api_key, timeout=30)
            if self.access_token:
                kite.set_access_token(self.access_token)
            return kite.ltp(query_symbols)
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Failed to fetch Zerodha LTP: {e}")
            from kiteconnect.exceptions import InputException
            from market_data.lookup import InvalidSymbolException, BrokerUnavailableException
            if isinstance(e, InputException) or "invalid" in str(e).lower() or "not found" in str(e).lower():
                raise InvalidSymbolException(str(e))
            raise BrokerUnavailableException(str(e))

    def is_token_expired(self, last_updated_at: datetime) -> bool:
        """
        Determines whether the Zerodha access token has expired.
        Zerodha tokens remain valid until approximately the next trading day around 07:30 AM IST.
        """
        if not last_updated_at:
            return True

        from zoneinfo import ZoneInfo
        from datetime import time
        import pytz

        ist = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(ist)

        # Convert last_updated_at to aware IST datetime
        if last_updated_at.tzinfo is None:
            # PostgreSQL naive DateTime is stored in local time (Asia/Kolkata)
            last_updated_ist = pytz.timezone("Asia/Kolkata").localize(last_updated_at)
        else:
            last_updated_ist = last_updated_at.astimezone(ist)

        # Check day difference in IST
        days_delta = (now_ist.date() - last_updated_ist.date()).days

        if days_delta == 0:
            return False  # Same day, still valid
        elif days_delta == 1:
            # Next day. Valid until 07:30 AM IST.
            cutoff_time = time(7, 30)
            return now_ist.time() >= cutoff_time
        else:
            return True  # Older than 1 day, expired.

    def verify_connection(self) -> bool:
        """
        Verifies that the access token is valid and active by calling kite.profile().
        """
        if not self.api_key or not self.access_token:
            raise ValidationException("API credentials (api_key/access_token) are required for verification.")
        try:
            kite = KiteConnect(api_key=self.api_key)
            kite.set_access_token(self.access_token)
            kite.profile()
            return True
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Zerodha broker connection verification failed: {e}")
            raise BrokerAdapterException("Broker connection verification failed. Stored session is invalid or broker is unreachable.", original_exception=e)
