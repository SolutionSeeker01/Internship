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

    def start_feed(self, loop: Any, subscription_tokens: List[int], on_tick_callback: Any, on_order_update_callback: Any = None) -> None:
        """
        Spawns the background WebSocket client feed for this broker.
        Registers on_tick_callback for market data ticks.
        Registers on_order_update_callback (if provided) for broker order fill/rejection events.
        """
        from kiteconnect import KiteTicker

        if not self.api_key or not self.access_token:
            raise ValidationException("API credentials (api_key/access_token) are required for starting feed.")

        if self.is_feed_running():
            logger.warning("Zerodha feed is already running.")
            return

        self._on_tick_callback = on_tick_callback
        self._on_order_update_callback = on_order_update_callback
        self._subscribed_tokens = set(subscription_tokens)

        try:
            self._kws = KiteTicker(api_key=self.api_key, access_token=self.access_token)

            # Register market data callbacks
            self._kws.on_connect = self._on_ticker_connect
            self._kws.on_ticks = self._on_ticker_ticks
            self._kws.on_error = self._on_ticker_error
            self._kws.on_close = self._on_ticker_close

            # Register order update callback if provided
            if on_order_update_callback is not None:
                self._kws.on_order_update = self._on_ticker_order_update
                logger.info("Zerodha KiteTicker: on_order_update callback registered for fill tracking.")

            logger.info("Connecting to Zerodha KiteTicker WebSocket...")
            self._kws.connect(threaded=True)
        except (KiteException, requests.exceptions.RequestException, ConnectionError) as e:
            logger.critical(f"Failed to start Zerodha KiteTicker: {e}", exc_info=True)
            self._kws = None
            self._on_tick_callback = None
            self._on_order_update_callback = None
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

    def _on_ticker_order_update(self, order_update: dict):
        """
        Receives raw Zerodha KiteTicker order update dict and forwards it to
        the registered on_order_update_callback (typically OrderManagerService.process_broker_order_update).

        The KiteTicker delivers order updates with the same field names as kite.orders() rows:
          order_id, status, filled_quantity, average_price, tradingsymbol, etc.
        """
        if not hasattr(self, "_on_order_update_callback") or not self._on_order_update_callback:
            return
        try:
            self._on_order_update_callback(order_update)
        except Exception as e:
            logger.error(f"ZerodhaBroker: error in on_order_update_callback: {e}", exc_info=True)

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

    def _get_client(self) -> KiteConnect:
        """
        Helper to construct and configure an authenticated KiteConnect client.
        """
        if not self.api_key or not self.access_token:
            raise ValidationException("API credentials (api_key/access_token) are required to communicate with the broker.")
        kite = KiteConnect(api_key=self.api_key)
        kite.set_access_token(self.access_token)
        return kite

    def verify_connection(self) -> bool:
        """
        Verifies that the access token is valid and active by calling kite.profile().
        """
        try:
            kite = self._get_client()
            kite.profile()
            return True
        except (KiteException, requests.exceptions.RequestException) as e:
            logger.error(f"Zerodha broker connection verification failed: {e}")
            raise BrokerAdapterException("Broker connection verification failed. Stored session is invalid or broker is unreachable.", original_exception=e)

    def get_profile(self) -> Dict[str, Any]:
        """
        Fetches user profile details from Zerodha.
        """
        try:
            kite = self._get_client()
            profile = kite.profile()
            return {
                "user_id": profile.get("user_id"),
                "user_name": profile.get("user_name")
            }
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha profile: {e}")
            raise BrokerAdapterException("Failed to retrieve user profile from broker.", original_exception=e)

    def get_margins(self) -> Dict[str, Any]:
        """
        Queries available funds and margin metrics from Zerodha.

        Returns a dict with the following keys per BaseBroker contract:
          - 'available_cash'   : float  — cash available for equity trades
          - 'utilized_margin'  : float  — margin already debited by open positions
          - 'collateral'       : float  — approved collateral value
          - 'net_value'        : float  — net account equity (equity_margins["net"])

        Raises BrokerAdapterException immediately if the broker response is missing
        the authoritative 'net' field rather than substituting a silent fallback.
        """
        try:
            kite = self._get_client()
            margins = kite.margins()
            equity_margins = margins.get("equity", {})

            # Fail fast if the authoritative net equity field is absent.
            # Do NOT fall back to available.cash — it is a different metric.
            if "net" not in equity_margins:
                raise BrokerAdapterException(
                    "Zerodha margins response is missing the required 'net' field in the "
                    "'equity' segment. Cannot compute net account value."
                )

            return {
                "available_cash": float(equity_margins.get("available", {}).get("cash", 0.0)),
                "utilized_margin": float(equity_margins.get("utilised", {}).get("debits", 0.0)),
                "collateral": float(equity_margins.get("available", {}).get("collateral", 0.0)),
                "net_value": float(equity_margins["net"])
            }
        except BrokerAdapterException:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha margins: {e}")
            raise BrokerAdapterException("Failed to retrieve margin stats from broker.", original_exception=e)

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Queries today's trading positions from Zerodha (net positions).
        """
        try:
            kite = self._get_client()
            positions_data = kite.positions()
            # We map "net" positions as they represent today's active exposures
            net_positions = positions_data.get("net", [])
            
            mapped_positions = []
            for pos in net_positions:
                mapped_positions.append({
                    "symbol": pos.get("tradingsymbol"),
                    "exchange": pos.get("exchange"),
                    "quantity": int(pos.get("quantity", 0)),
                    "average_price": float(pos.get("average_price", 0.0)),
                    "last_price": float(pos.get("last_price", 0.0)),
                    "pnl": float(pos.get("pnl", 0.0))
                })
            return mapped_positions
        except Exception as e:
            logger.error(f"Failed to fetch Zerodha positions: {e}")
            raise BrokerAdapterException("Failed to retrieve trading positions from broker.", original_exception=e)

    def place_order(self, order_spec: Any, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Submits an order specification to Zerodha KiteConnect.
        """
        try:
            kite = self._get_client()
            
            # Extract order spec attributes
            symbol = getattr(order_spec, "symbol", "")
            exchange = getattr(order_spec, "exchange", "NSE")
            action = getattr(order_spec, "action", "BUY")
            quantity = getattr(order_spec, "quantity", 1)
            order_type = getattr(order_spec, "order_type", "MARKET")
            product = getattr(order_spec, "product", "MIS")
            price = float(getattr(order_spec, "price", 0.0)) if getattr(order_spec, "price", None) else None
            trigger_price = float(getattr(order_spec, "trigger_price", 0.0)) if getattr(order_spec, "trigger_price", None) else None

            # Map transaction type
            trans_type = kite.TRANSACTION_TYPE_BUY if action == "BUY" else kite.TRANSACTION_TYPE_SELL
            
            # Map order type
            ord_type = kite.ORDER_TYPE_MARKET
            if order_type == "LIMIT":
                ord_type = kite.ORDER_TYPE_LIMIT
            elif order_type == "SL":
                ord_type = kite.ORDER_TYPE_SL
            elif order_type == "SL_MARKET":
                ord_type = kite.ORDER_TYPE_SLM

            # Map product
            prod_type = kite.PRODUCT_MIS if product in ("MIS", "INTRADAY") else kite.PRODUCT_CNC

            order_id = kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=symbol,
                transaction_type=trans_type,
                quantity=quantity,
                product=prod_type,
                order_type=ord_type,
                price=price,
                trigger_price=trigger_price,
                tag=idempotency_key[:20] if idempotency_key else None
            )

            return {
                "broker_order_id": str(order_id),
                "status": "SUBMITTED"
            }
        except Exception as e:
            logger.error(f"Zerodha place_order failed for symbol {getattr(order_spec, 'symbol', '')}: {e}")
            raise BrokerAdapterException(f"Broker order submission failed: {e}", original_exception=e)

    def get_order_by_id(self, broker_order_id: str) -> Optional[Dict[str, Any]]:
        """
        Queries Zerodha for an existing order by its broker_order_id.
        """
        try:
            kite = self._get_client()
            history = kite.order_history(order_id=broker_order_id)
            if history:
                latest = history[-1]
                return {
                    "broker_order_id": str(latest.get("order_id")),
                    "status": str(latest.get("status", "SUBMITTED")),
                    "symbol": str(latest.get("tradingsymbol", "")),
                    "exchange": str(latest.get("exchange", "NSE")),
                    "action": str(latest.get("transaction_type", "BUY")),
                    "quantity": int(latest.get("quantity", 0)),
                    "price": float(latest.get("price", 0.0))
                }
            return None
        except Exception as e:
            logger.warning(f"Zerodha get_order_by_id failed for order {broker_order_id}: {e}")
            raise BrokerAdapterException(f"Order query failed: {e}", original_exception=e)

    def get_order_by_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        """
        Queries Zerodha for an existing order matching the given tag / idempotency_key.
        """
        try:
            kite = self._get_client()
            orders = kite.orders()
            search_tag = tag[:20] if tag else ""
            for ord_item in orders:
                if ord_item.get("tag") == search_tag:
                    return {
                        "broker_order_id": str(ord_item.get("order_id")),
                        "status": str(ord_item.get("status", "SUBMITTED")),
                        "symbol": str(ord_item.get("tradingsymbol", "")),
                        "exchange": str(ord_item.get("exchange", "NSE")),
                        "action": str(ord_item.get("transaction_type", "BUY")),
                        "quantity": int(ord_item.get("quantity", 0)),
                        "price": float(ord_item.get("price", 0.0))
                    }
            return None
        except Exception as e:
            logger.warning(f"Zerodha get_order_by_tag failed for tag {tag}: {e}")
            raise BrokerAdapterException(f"Order tag query failed: {e}", original_exception=e)

    def cancel_order(self, broker_order_id: str) -> bool:
        """
        Cancels an open order at Zerodha by its broker_order_id.

        Uses the variety='regular' as the default; SL and CO orders require different
        varieties but the platform currently only places regular (MIS/CNC) orders.

        :param broker_order_id: The Zerodha order_id string to cancel.
        :return: True if the cancellation request was accepted by the broker.
        :raises BrokerAdapterException: If the cancellation API call fails.
        """
        try:
            kite = self._get_client()
            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=broker_order_id)
            logger.info(f"ZerodhaBroker: cancel_order accepted for broker_order_id={broker_order_id}")
            return True
        except Exception as e:
            logger.error(f"ZerodhaBroker: cancel_order failed for broker_order_id={broker_order_id}: {e}")
            raise BrokerAdapterException(
                f"Failed to cancel order {broker_order_id} at Zerodha.",
                original_exception=e
            )

    def modify_order(self, broker_order_id: str, modifications: Dict[str, Any]) -> bool:
        """
        Modifies an open order at Zerodha.

        Supported modification keys (per KiteConnect API):
          - 'price'           : float — new limit price
          - 'trigger_price'   : float — new trigger price (for SL orders)
          - 'quantity'        : int   — new quantity
          - 'order_type'      : str   — new order type (LIMIT, SL, etc.)

        :param broker_order_id: The Zerodha order_id string to modify.
        :param modifications: Dict of fields to update.
        :return: True if the modification was accepted by the broker.
        :raises BrokerAdapterException: If the modification API call fails.
        """
        try:
            kite = self._get_client()
            params = {"order_id": broker_order_id, "variety": kite.VARIETY_REGULAR}
            if "price" in modifications:
                params["price"] = float(modifications["price"])
            if "trigger_price" in modifications:
                params["trigger_price"] = float(modifications["trigger_price"])
            if "quantity" in modifications:
                params["quantity"] = int(modifications["quantity"])
            if "order_type" in modifications:
                params["order_type"] = str(modifications["order_type"])

            kite.modify_order(**params)
            logger.info(f"ZerodhaBroker: modify_order accepted for broker_order_id={broker_order_id}, modifications={modifications}")
            return True
        except Exception as e:
            logger.error(f"ZerodhaBroker: modify_order failed for broker_order_id={broker_order_id}: {e}")
            raise BrokerAdapterException(
                f"Failed to modify order {broker_order_id} at Zerodha.",
                original_exception=e
            )


