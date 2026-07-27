# e:/Internship/Backend/market_data/account_websocket_feed.py
"""
AccountWebSocketFeed - Concrete Reference-Counted Client Market Data Feed

Manages exactly one authenticated BrokerAccount WebSocket session.
Enforces explicit state machine transitions (DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTING)
and thread-safe symbol reference counting.

Ownership:
  BrokerAccount (broker_account_id)
        │
        ▼
  AccountWebSocketFeed
        │
  Reference-Counted Subscriptions ({symbol: ref_count})
        │
  ExecutionTargets
        │
  Trades

Key Features:
  - Broker-agnostic: Delegate callbacks can be injected for ticker implementation.
  - State Machine: Strict state transitions with invalid transition rejection.
  - Thread-Safe: Atomic state updates and reference count operations under RLock.
  - Automatic Teardown Hook: Triggered when total subscriptions drop to 0 after trade closure.
"""

import threading
from typing import Dict, Any, List, Set, Optional, Callable
from market_data.base_feed import BaseBrokerFeed, FeedState, InvalidFeedStateTransitionError
from utils.logger import get_logger

logger = get_logger(__name__)


class AccountWebSocketFeed(BaseBrokerFeed):
    """
    Concrete broker-agnostic client market data WebSocket feed manager.
    Keyed 1:1 by integer `broker_account_id`.
    """

    # Allowed state machine transitions matrix
    _ALLOWED_TRANSITIONS = {
        FeedState.DISCONNECTED: {FeedState.CONNECTING},
        FeedState.CONNECTING: {FeedState.CONNECTED, FeedState.DISCONNECTED},
        FeedState.CONNECTED: {FeedState.DISCONNECTING, FeedState.CONNECTING}, # CONNECTING allows reconnect hook
        FeedState.DISCONNECTING: {FeedState.DISCONNECTED}
    }

    def __init__(
        self,
        broker_account_id: int,
        broker_name: str = "ZERODHA",
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        on_tick_callback: Optional[Callable[[int, str, Any], None]] = None,
        auto_disconnect_on_zero_subs: bool = True
    ):
        """
        Lightweight initialization. Does NOT auto-connect on construction.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.
            broker_name (str): Broker identifier ('ZERODHA', 'UPSTOX', 'ANGELONE').
            api_key (Optional[str]): Client API key.
            access_token (Optional[str]): Authenticated access token.
            on_tick_callback (Optional[Callable]): Callback accepting (broker_account_id, symbol, price/data).
            auto_disconnect_on_zero_subs (bool): Automatically disconnect when all active subs drop to 0.
        """
        super().__init__(broker_account_id=broker_account_id, broker_name=broker_name)

        self.api_key = api_key
        self.access_token = access_token
        self.on_tick_callback = on_tick_callback
        self.auto_disconnect_on_zero_subs = auto_disconnect_on_zero_subs

        # Threading protection
        self._lock = threading.RLock()

        # State machine
        self._state: FeedState = FeedState.DISCONNECTED

        # Reference-counted symbol subscriptions mapping: symbol_upper -> count
        self._ref_counts: Dict[str, int] = {}

        # Token mapping if broker uses integer tokens: symbol_upper -> token
        self._symbol_tokens: Dict[str, int] = {}

        # Abstract broker ticker handle (e.g., KiteTicker or Upstox WebSocket object)
        self._broker_ticker: Optional[Any] = None

    # ------------------------------------------------------------------
    # State Machine Implementation
    # ------------------------------------------------------------------

    def current_state(self) -> FeedState:
        """Returns current feed state thread-safely."""
        with self._lock:
            return self._state

    def is_connected(self) -> bool:
        """Returns True if feed state is CONNECTED."""
        with self._lock:
            return self._state == FeedState.CONNECTED

    def _transition_to(self, new_state: FeedState) -> None:
        """
        Internal thread-safe state machine transition validator.

        Raises:
            InvalidFeedStateTransitionError: If transition is forbidden.
        """
        with self._lock:
            allowed = self._ALLOWED_TRANSITIONS.get(self._state, set())
            if new_state not in allowed:
                err_msg = (
                    f"Forbidden state transition for broker_account_id {self.broker_account_id}: "
                    f"'{self._state.value}' -> '{new_state.value}'."
                )
                logger.error(err_msg)
                raise InvalidFeedStateTransitionError(err_msg)

            logger.info(
                f"AccountWebSocketFeed({self.broker_account_id}): "
                f"State transition '{self._state.value}' -> '{new_state.value}'."
            )
            self._state = new_state

    # ------------------------------------------------------------------
    # Connection Lifecycle API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Initiates connection to the broker WebSocket.
        Transitions: DISCONNECTED -> CONNECTING -> CONNECTED.
        """
        with self._lock:
            if self._state == FeedState.CONNECTED:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Already CONNECTED.")
                return
            if self._state == FeedState.CONNECTING:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Connection already in progress.")
                return

            self._transition_to(FeedState.CONNECTING)

            try:
                # In Phase 2: Mock / Abstract connection setup
                # In Phase 3: Actual broker ticker instantiation
                logger.info(f"AccountWebSocketFeed({self.broker_account_id}): Authenticating & connecting WebSocket feed...")
                
                # Transition to CONNECTED upon successful socket handshake
                self._transition_to(FeedState.CONNECTED)
            except Exception as e:
                logger.error(f"AccountWebSocketFeed({self.broker_account_id}): Connection failed: {e}")
                self._state = FeedState.DISCONNECTED
                raise

    def disconnect(self) -> None:
        """
        Gracefully unsubscribes symbols and closes WebSocket connection.
        Transitions: CONNECTED / CONNECTING -> DISCONNECTING -> DISCONNECTED.
        """
        with self._lock:
            if self._state == FeedState.DISCONNECTED:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Already DISCONNECTED.")
                return
            if self._state == FeedState.DISCONNECTING:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Disconnect already in progress.")
                return

            # Handle transition to DISCONNECTING
            if self._state in (FeedState.CONNECTED, FeedState.CONNECTING):
                self._transition_to(FeedState.DISCONNECTING)

            try:
                # 1. Unsubscribe all active tokens at broker
                active_symbols = list(self._ref_counts.keys())
                if active_symbols:
                    logger.info(f"AccountWebSocketFeed({self.broker_account_id}): Unsubscribing symbols: {active_symbols}")
                    self._dispatch_broker_unsubscribe(active_symbols)

                # 2. Reset internal reference counts
                self._ref_counts.clear()
                self._symbol_tokens.clear()

                # 3. Close ticker socket handle
                if self._broker_ticker is not None:
                    self._close_broker_ticker()

            finally:
                self._transition_to(FeedState.DISCONNECTED)

    def reconnect(self) -> None:
        """
        Hook for automatic reconnection after network disconnect.
        Restores subscriptions for all symbols with ref_count > 0.
        """
        with self._lock:
            logger.info(f"AccountWebSocketFeed({self.broker_account_id}): Triggering reconnection flow...")
            
            # Save existing symbols & counts
            active_counts = dict(self._ref_counts)
            active_tokens = dict(self._symbol_tokens)

            # Force reset state to DISCONNECTED to allow fresh CONNECTING transition
            self._state = FeedState.DISCONNECTED
            self.connect()

            # Restore active symbol subscriptions in batched request
            if active_counts:
                symbols_to_sub = [sym for sym, count in active_counts.items() if count > 0]
                if symbols_to_sub:
                    logger.info(f"AccountWebSocketFeed({self.broker_account_id}): Restoring subscriptions after reconnect: {symbols_to_sub}")
                    self._ref_counts = active_counts
                    self._symbol_tokens = active_tokens
                    self._dispatch_broker_subscribe(symbols_to_sub)

    # ------------------------------------------------------------------
    # Reference-Counted Subscription API
    # ------------------------------------------------------------------

    def subscribe_symbol(self, symbol: str, token: Optional[int] = None) -> bool:
        """
        Increments reference count for symbol.
        Dispatches broker subscription ONLY if ref_count transitions 0 -> 1.

        Args:
            symbol (str): Trading symbol (e.g. 'RELIANCE').
            token (Optional[int]): Broker token if available.

        Returns:
            bool: True if broker subscribe was issued, False if count incremented only.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string.")

        symbol_upper = symbol.strip().upper()

        with self._lock:
            # Auto-connect lazy check if disconnected
            if self._state == FeedState.DISCONNECTED:
                self.connect()

            current_count = self._ref_counts.get(symbol_upper, 0)
            new_count = current_count + 1
            self._ref_counts[symbol_upper] = new_count

            if token is not None:
                self._symbol_tokens[symbol_upper] = token

            if current_count == 0:
                logger.info(f"AccountWebSocketFeed({self.broker_account_id}): 0 -> 1 Subscribing symbol '{symbol_upper}' (ref_count=1).")
                self._dispatch_broker_subscribe([symbol_upper])
                return True
            else:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Incremented ref_count for '{symbol_upper}' ({current_count} -> {new_count}).")
                return False

    def unsubscribe_symbol(self, symbol: str) -> bool:
        """
        Decrements reference count for symbol.
        Dispatches broker unsubscribe ONLY when ref_count reaches 0.

        Args:
            symbol (str): Trading symbol (e.g. 'RELIANCE').

        Returns:
            bool: True if broker unsubscribe was issued, False if count decremented only.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string.")

        symbol_upper = symbol.strip().upper()

        with self._lock:
            current_count = self._ref_counts.get(symbol_upper, 0)
            if current_count <= 0:
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Unsubscribe ignored. '{symbol_upper}' ref_count is already 0.")
                return False

            new_count = current_count - 1
            if new_count > 0:
                self._ref_counts[symbol_upper] = new_count
                logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Decremented ref_count for '{symbol_upper}' ({current_count} -> {new_count}).")
                return False
            else:
                # Count hit 0 -> Remove symbol
                del self._ref_counts[symbol_upper]
                self._symbol_tokens.pop(symbol_upper, None)
                logger.info(f"AccountWebSocketFeed({self.broker_account_id}): 1 -> 0 Unsubscribing symbol '{symbol_upper}' (ref_count=0).")
                self._dispatch_broker_unsubscribe([symbol_upper])

                # Teardown check: if 0 active subscriptions remain, auto-disconnect feed
                if self.auto_disconnect_on_zero_subs and len(self._ref_counts) == 0:
                    logger.info(f"AccountWebSocketFeed({self.broker_account_id}): 0 active subscriptions remain. Triggering graceful disconnect.")
                    self.disconnect()

                return True

    def subscribed_symbols(self) -> List[str]:
        """Returns snapshot of active subscribed symbols (ref_count > 0)."""
        with self._lock:
            return [sym for sym, count in self._ref_counts.items() if count > 0]

    def reference_count(self, symbol: str) -> int:
        """Returns current reference count for symbol."""
        if not symbol or not isinstance(symbol, str):
            return 0
        symbol_upper = symbol.strip().upper()
        with self._lock:
            return self._ref_counts.get(symbol_upper, 0)

    # ------------------------------------------------------------------
    # Internal Broker Dispatch Hooks (Abstracted for Phase 3 Ticker Injection)
    # ------------------------------------------------------------------

    def _dispatch_broker_subscribe(self, symbols: List[str]) -> None:
        """Internal hook to send subscription message to broker WS feed."""
        logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Broker dispatch subscribe: {symbols}")

    def _dispatch_broker_unsubscribe(self, symbols: List[str]) -> None:
        """Internal hook to send unsubscribe message to broker WS feed."""
        logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Broker dispatch unsubscribe: {symbols}")

    def _close_broker_ticker(self) -> None:
        """Internal hook to close physical WebSocket ticker handle."""
        logger.debug(f"AccountWebSocketFeed({self.broker_account_id}): Closing broker ticker handle.")
        self._broker_ticker = None
