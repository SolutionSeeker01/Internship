# e:/Internship/Backend/market_data/base_feed.py
"""
BaseBrokerFeed - Abstract Broker-Agnostic Market Data Feed Interface

Defines the contract that any broker-specific market data WebSocket feed adapter
(e.g., Zerodha, Upstox, Angel One) must fulfill.

Key Design Principles:
  - Broker-agnostic lifecycle & subscription interface.
  - Zero hardcoded broker specificities.
  - Pluggable into AccountFeedManager and ScopedTickRouter.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Set, Optional, Callable
from enum import Enum


class FeedState(str, Enum):
    """Explicit, immutable feed lifecycle states."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTING = "DISCONNECTING"


class BaseBrokerFeedException(Exception):
    """Base exception for broker feed operations."""
    pass


class InvalidFeedStateTransitionError(BaseBrokerFeedException):
    """Raised when an illegal lifecycle state transition is attempted."""
    pass


class BaseBrokerFeed(ABC):
    """
    Abstract Base Class for all broker WebSocket market data feed adapters.
    Keyed 1:1 by integer broker_account_id.
    """

    def __init__(self, broker_account_id: int, broker_name: str = "GENERIC"):
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        self.broker_account_id: int = broker_account_id
        self.broker_name: str = broker_name.upper().strip()

    @abstractmethod
    def connect(self) -> None:
        """Initiates async/threaded connection to the broker WebSocket."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully unsubscribes symbols and closes the WebSocket connection."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Returns True if the feed state is CONNECTED."""
        pass

    @abstractmethod
    def current_state(self) -> FeedState:
        """Returns the current FeedState enum value."""
        pass

    @abstractmethod
    def subscribe_symbol(self, symbol: str, token: Optional[int] = None) -> bool:
        """
        Increments reference count for symbol and subscribes at broker if count transitions 0 -> 1.
        
        Args:
            symbol (str): Mandatory symbol string (e.g. 'RELIANCE').
            token (Optional[int]): Broker-specific instrument token if required.

        Returns:
            bool: True if new broker subscription request was issued, False if count incremented only.
        """
        pass

    @abstractmethod
    def unsubscribe_symbol(self, symbol: str) -> bool:
        """
        Decrements reference count for symbol and unsubscribes at broker when count hits 0.

        Args:
            symbol (str): Mandatory symbol string (e.g. 'RELIANCE').

        Returns:
            bool: True if broker unsubscribe request was issued, False if stream kept active.
        """
        pass

    @abstractmethod
    def subscribed_symbols(self) -> List[str]:
        """Returns snapshot list of all currently active subscribed symbols (ref_count > 0)."""
        pass

    @abstractmethod
    def reference_count(self, symbol: str) -> int:
        """Returns current active reference count for the symbol."""
        pass
