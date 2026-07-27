# e:/Internship/Backend/market_data/account_feed_manager.py
"""
AccountFeedManager - Client Market Data Feed Registry Manager

Manages the lifecycle and thread-safe registry of per-account market data feeds.
Strictly keyed by `broker_account_id` to guarantee that exactly one broker WebSocket
connection exists per authenticated broker account.

Hierarchy:
  BrokerAccount (broker_account_id)
        │
        ▼
  AccountWebSocketFeed (Placeholder / Abstract Feed managed by Manager)
        │
  ExecutionTargets
        │
  Trades

Responsibilities:
  - Thread-safe lazy creation of client feeds by `broker_account_id`.
  - Lookup and retrieval of existing feeds.
  - Controlled teardown and removal of feeds when inactive.
  - Zero coupling with trade logic, tick routing, order manager, or subscriptions.
"""

import threading
from typing import Dict, Any, Optional, List, Callable
from market_data.account_websocket_feed import AccountWebSocketFeed
from utils.logger import get_logger

logger = get_logger(__name__)


class AccountFeedManagerException(Exception):
    """Base exception for AccountFeedManager operations."""
    pass


class DuplicateFeedError(AccountFeedManagerException):
    """Raised when attempting to manually register a feed under an existing broker_account_id."""
    pass


class AccountFeedManager:
    """
    Thread-safe manager for client broker market data feed instances.
    Keyed exclusively by integer `broker_account_id`.
    """

    def __init__(self, feed_factory: Optional[Callable[..., AccountWebSocketFeed]] = None):
        """
        Args:
            feed_factory (Optional[Callable]): Optional custom factory callable used to
                instantiate new feed instances when get_or_create_feed is invoked.
        """
        self._feeds: Dict[int, AccountWebSocketFeed] = {}
        self._lock = threading.RLock()
        self._feed_factory = feed_factory

    def get_feed(self, broker_account_id: int) -> Optional[AccountWebSocketFeed]:
        """
        Retrieves an active feed by broker_account_id.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.

        Returns:
            Optional[AccountWebSocketFeed]: Active feed instance if registered, otherwise None.
        """
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        with self._lock:
            return self._feeds.get(broker_account_id)

    def has_feed(self, broker_account_id: int) -> bool:
        """
        Checks if a feed exists for the specified broker_account_id.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.

        Returns:
            bool: True if feed exists, False otherwise.
        """
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        with self._lock:
            return broker_account_id in self._feeds

    def get_or_create_feed(
        self,
        broker_account_id: int,
        feed_builder: Optional[Callable[[int], AccountWebSocketFeed]] = None,
        **kwargs: Any
    ) -> AccountWebSocketFeed:
        """
        Retrieves an existing feed or lazily instantiates a new feed under thread-safe locking.
        Prevents duplicate feed creation under concurrent calls for the same broker_account_id.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.
            feed_builder (Optional[Callable]): Optional per-call builder override.
            **kwargs: Extra parameters passed to builder/factory if new feed is created.

        Returns:
            AccountWebSocketFeed: The active or newly created feed instance.
        """
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        with self._lock:
            # Double-check pattern under lock
            if broker_account_id in self._feeds:
                logger.debug(f"AccountFeedManager: Reusing existing feed for broker_account_id {broker_account_id}.")
                return self._feeds[broker_account_id]

            logger.info(f"AccountFeedManager: Creating new feed for broker_account_id {broker_account_id}.")

            # 1. Per-call builder override
            if feed_builder is not None:
                feed = feed_builder(broker_account_id, **kwargs)
            # 2. Manager-level factory
            elif self._feed_factory is not None:
                feed = self._feed_factory(broker_account_id, **kwargs)
            # 3. Default AccountWebSocketFeed instantiation
            else:
                feed = AccountWebSocketFeed(broker_account_id=broker_account_id, **kwargs)

            self._feeds[broker_account_id] = feed
            return feed

    def register_feed(self, broker_account_id: int, feed_instance: AccountWebSocketFeed) -> None:
        """
        Manually registers an externally instantiated feed object under a broker_account_id.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.
            feed_instance (AccountWebSocketFeed): The feed instance object.

        Raises:
            DuplicateFeedError: If a feed is already registered for this broker_account_id.
        """
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")
        if feed_instance is None:
            raise ValueError("feed_instance cannot be None.")

        with self._lock:
            if broker_account_id in self._feeds:
                raise DuplicateFeedError(
                    f"Feed already registered for broker_account_id {broker_account_id}."
                )
            self._feeds[broker_account_id] = feed_instance
            logger.info(f"AccountFeedManager: Manually registered feed for broker_account_id {broker_account_id}.")

    def remove_feed(self, broker_account_id: int, stop_feed: bool = True) -> Optional[AccountWebSocketFeed]:
        """
        Removes and unregisters a feed instance for a broker_account_id.

        Args:
            broker_account_id (int): Primary key ID of the BrokerAccount.
            stop_feed (bool): If True, invokes stop()/disconnect() on the feed if implemented.

        Returns:
            Optional[Any]: The removed feed instance, or None if not found.
        """
        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        with self._lock:
            feed = self._feeds.pop(broker_account_id, None)
            if feed is None:
                logger.debug(f"AccountFeedManager: No feed found to remove for broker_account_id {broker_account_id}.")
                return None

            logger.info(f"AccountFeedManager: Removed feed for broker_account_id {broker_account_id}.")

            if stop_feed:
                self._stop_feed_instance(feed, broker_account_id)

            return feed

    def active_feed_count(self) -> int:
        """
        Returns the current number of active feeds registered in the manager.

        Returns:
            int: Number of active registered feeds.
        """
        with self._lock:
            return len(self._feeds)

    def get_all_active_broker_account_ids(self) -> List[int]:
        """
        Returns a snapshot list of all active registered broker_account_ids.

        Returns:
            List[int]: List of broker_account_id integers.
        """
        with self._lock:
            return list(self._feeds.keys())

    def clear(self, stop_all: bool = True) -> None:
        """
        Clears all registered feeds from the manager. Useful for testing and shutdown.

        Args:
            stop_all (bool): If True, invokes stop()/disconnect() on all active feeds.
        """
        with self._lock:
            if stop_all:
                for broker_account_id, feed in list(self._feeds.items()):
                    self._stop_feed_instance(feed, broker_account_id)
            self._feeds.clear()
            logger.info("AccountFeedManager: Registry cleared completely.")

    def _stop_feed_instance(self, feed: Any, broker_account_id: int) -> None:
        """Helper to invoke stop/disconnect methods gracefully on feed object if present."""
        try:
            if hasattr(feed, "disconnect") and callable(feed.disconnect):
                feed.disconnect()
            elif hasattr(feed, "stop") and callable(feed.stop):
                feed.stop()
        except Exception as e:
            logger.error(f"AccountFeedManager: Error stopping feed for broker_account_id {broker_account_id}: {e}")


class GenericAccountFeed:
    """
    Lightweight default feed wrapper used prior to Phase 2 AccountWebSocketFeed implementation.
    """
    def __init__(self, broker_account_id: int, **kwargs: Any):
        self.broker_account_id = broker_account_id
        self.is_connected = False
        self.metadata = kwargs

    def connect(self) -> None:
        self.is_connected = True

    def disconnect(self) -> None:
        self.is_connected = False
