from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from schemas.candles import HistoricalCandle

class BaseBroker(ABC):
    """
    Abstract Base Class defining the unified interface for all broker integrations.
    Phase 1 scopes strictly to Broker Authentication and Session Onboarding.
    """

    @abstractmethod
    def get_login_url(self, state: str) -> str:
        """
        Generates the secure OAuth login/redirect URL to initiate authentication with the broker.
        The adapter instance is expected to carry its own static configurations.
        
        :param state: A secure state token to prevent CSRF.
        :return: Plaintext redirect URL.
        """
        pass

    @abstractmethod
    def handle_callback(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handles the authentication callback redirect from the broker, exchanging request
        tokens or auth codes for long-lived session access tokens.
        The adapter instance is expected to carry its own static configurations.
        
        :param params: Dict containing all redirect query parameters (e.g., code, request_token, state).
        :return: Dict containing session tokens (e.g., access_token, refresh_token, broker_user_id).
        """
        pass

    @abstractmethod
    def is_session_valid(self, api_key: str, access_token: str) -> bool:
        """
        Validates whether the current stored session access token remains fresh and active.
        
        :param api_key: The client/app API key.
        :param access_token: The session access token.
        :return: True if session is active and valid, False otherwise.
        """
        pass

    @abstractmethod
    def is_token_expired(self, last_updated_at: datetime) -> bool:
        """
        Determines whether the access token has expired according to the broker's specific session lifecycle.
        
        :param last_updated_at: The timestamp when the access token was generated/stored.
        :return: True if the token is expired, False otherwise.
        """
        pass

    @abstractmethod
    def verify_connection(self) -> bool:
        """
        Verifies that the broker connection is valid and usable by executing a lightweight authenticated call.
        
        :return: True if the verification succeeded.
        :raises BrokerAdapterException: If the session is invalid or broker is unreachable.
        """
        pass

    @abstractmethod
    def get_historical_candles(
        self,
        instrument_token: int,
        interval: str,
        from_date: datetime,
        to_date: datetime
    ) -> List[HistoricalCandle]:
        """
        Retrieves historical candlestick data for the specified instrument token.
        The adapter instance is expected to carry its own API credentials.
        """
        pass

    @abstractmethod
    def start_feed(self, loop: Any, subscription_tokens: List[int], on_tick_callback: Any) -> None:
        """
        Spawns the background WebSocket client feed for this broker.
        When a new tick is received and normalized, it executes on_tick_callback(normalized_data).
        """
        pass

    @abstractmethod
    def stop_feed(self) -> None:
        """
        Terminates the WebSocket client feed connection and resets connection structures.
        """
        pass

    @abstractmethod
    def update_subscriptions(self, subscription_tokens: List[int]) -> None:
        """
        Dynamically updates active ticker subscriptions.
        """
        pass

    @abstractmethod
    def is_feed_running(self) -> bool:
        """
        Returns True if the WebSocket client feed is active and running.
        """
        pass

    @abstractmethod
    def get_instruments_metadata(self, exchange: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches the master instrument list from the broker.
        Each dictionary in the returned list should contain:
        - 'instrument_token': int/str
        - 'exchange': str
        - 'tradingsymbol': str
        - 'name': str
        - 'segment': str
        - 'instrument_type': str
        """
        pass

    @abstractmethod
    def get_ltp(self, query_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Queries the last traded price for the given exchange:symbol query strings.
        Returns a dictionary mapping each query_symbol to a dictionary containing:
        - 'last_price': float
        """
        pass

    @abstractmethod
    def get_profile(self) -> Dict[str, Any]:
        """
        Fetches user profile details from the broker.
        Returns a standardized dictionary containing:
        - 'user_id': str
        - 'user_name': str
        """
        pass

    @abstractmethod
    def get_margins(self) -> Dict[str, Any]:
        """
        Queries available funds and margin metrics from the broker.
        Returns a standardized dictionary containing:
        - 'available_cash': float
        - 'utilized_margin': float
        - 'collateral': float
        """
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Queries today's trading positions from the broker.
        """
        pass

    @abstractmethod
    def place_order(self, order_spec: Any, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Submits an order specification to the broker.
        Returns dictionary containing:
        - 'broker_order_id': str
        - 'status': str (e.g. 'SUBMITTED', 'OPEN', 'COMPLETE')
        """
        pass

    @abstractmethod
    def get_order_by_id(self, broker_order_id: str) -> Optional[Dict[str, Any]]:
        """
        Queries broker for an existing order by its broker_order_id.
        Returns standardized order dict if found, or None if not found.
        """
        pass

    @abstractmethod
    def get_order_by_tag(self, tag: str) -> Optional[Dict[str, Any]]:
        """
        Queries broker for an existing order by its tag / idempotency_key.
        Returns standardized order dict if found, or None if not found.
        """
        pass


