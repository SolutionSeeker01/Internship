# Backend/services/runtime/runtime_coordinator.py
"""
Runtime Coordinator - Top-Level Runtime Infrastructure Lifecycle Orchestration Engine

Implements Stage 7B Final Integration of phase7_runtime_integration_plan.md and respects
Section 5.15 and Section 12 of ARCHITECTURE_REFERENCE.md (v1.5.3).

Responsibilities:
  1. Phase 1 (initialize): Construct OrderManagerRegistry, StartupRecoveryService, BrokerEventRouter,
     and TickRouter, wiring dependency composition callbacks.
  2. Phase 2 (start): Execute startup crash recovery and transition runtime to OPERATIONAL state.
  3. Centralize OrderManagerService factory creation.
  4. Expose controlled access to runtime infrastructure (registry, event router, tick router).
  5. Orchestrate graceful runtime shutdown.

Constraints:
  - NO trading business logic or state machine transitions.
  - Infrastructure lifecycle coordinator only.
"""

from typing import Dict, Any, Optional, Callable
from database.db import SessionLocal
from services.order_manager.order_manager_service import OrderManagerService
from services.runtime.order_manager_registry import OrderManagerRegistry
from services.runtime.startup_recovery_service import StartupRecoveryService
from services.runtime.broker_event_router import BrokerEventRouter
from services.runtime.tick_router import TickRouter
from market_data.account_feed_manager import AccountFeedManager
from market_data.account_websocket_feed import AccountWebSocketFeed, FeedState
from utils.logger import get_logger

logger = get_logger(__name__)


class RuntimeCoordinatorException(Exception):
    """Base exception for RuntimeCoordinator failures."""
    pass


class AlreadyInitializedException(RuntimeCoordinatorException):
    """Raised when initialize() or start() is called out of order."""
    pass


class NotInitializedException(RuntimeCoordinatorException):
    """Raised when runtime services are accessed before initialization/startup."""
    pass


class RuntimeCoordinator:
    """
    Master top-level coordinator managing startup, recovery, dependency composition,
    event routing, tick routing, client feed lifecycle, and shutdown lifecycle for the backend trading platform.
    """

    def __init__(
        self,
        broker_factory: Any,
        session_factory: Optional[Callable[[], Any]] = None,
        subscription_callback: Optional[Callable[[str], None]] = None,
        feed_manager: Optional[AccountFeedManager] = None
    ):
        """
        Args:
            broker_factory (Any): Central BrokerFactory instance for manager creation.
            session_factory (Optional[Callable[[], Any]]): DB Session factory (defaults to SessionLocal).
            subscription_callback (Optional[Callable[[str], None]]): Optional callback function for market data subscriptions.
            feed_manager (Optional[AccountFeedManager]): Client market data feed registry manager.
        """
        if broker_factory is None:
            raise ValueError("broker_factory is required for RuntimeCoordinator.")

        self.broker_factory = broker_factory
        self.session_factory = session_factory or SessionLocal
        self.subscription_callback = subscription_callback
        self.feed_manager = feed_manager

        self.registry: Optional[OrderManagerRegistry] = None
        self.startup_recovery_service: Optional[StartupRecoveryService] = None
        self.broker_event_router: Optional[BrokerEventRouter] = None
        self.tick_router: Optional[TickRouter] = None
        
        self._is_initialized: bool = False
        self._is_running: bool = False

    def initialize(self) -> None:
        """
        Phase 1 — Infrastructure Construction & Dependency Composition.

        Instantiates runtime registry, recovery service, broker event router, tick router,
        and account feed manager, wiring all internal dependencies. No recovery execution occurs during this phase.

        Raises:
            AlreadyInitializedException: If called when runtime infrastructure is already initialized.
        """
        if self._is_initialized:
            logger.warning("Attempted to initialize RuntimeCoordinator when already initialized.")
            raise AlreadyInitializedException("RuntimeCoordinator infrastructure is already initialized.")

        logger.info("Phase 1: Initializing RuntimeCoordinator infrastructure & dependency wiring...")

        try:
            # 1. Instantiate OrderManagerRegistry
            self.registry = OrderManagerRegistry()

            # 2. Instantiate AccountFeedManager if not provided
            if self.feed_manager is None:
                self.feed_manager = AccountFeedManager()

            # 3. Instantiate StartupRecoveryService injecting manager_factory callback & feed_manager
            self.startup_recovery_service = StartupRecoveryService(
                registry=self.registry,
                manager_factory=self._create_manager_instance,
                subscription_callback=self.subscription_callback,
                feed_manager=self.feed_manager
            )

            # 4. Instantiate BrokerEventRouter
            self.broker_event_router = BrokerEventRouter(registry=self.registry)

            # 5. Instantiate TickRouter
            self.tick_router = TickRouter(registry=self.registry)

            self._is_initialized = True
            logger.info("Phase 1: RuntimeCoordinator infrastructure initialized successfully.")

        except Exception as e:
            logger.error(f"RuntimeCoordinator Phase 1 initialization failed: {e}", exc_info=True)
            self.shutdown()
            raise RuntimeCoordinatorException(f"RuntimeCoordinator initialization failed: {e}") from e

    def start(self) -> Dict[str, Any]:
        """
        Phase 2 — Runtime Startup & Crash Recovery Execution.

        Executes startup crash recovery, restores active trades, and transitions runtime to operational state.

        Returns:
            Dict[str, Any]: Diagnostic recovery summary report.

        Raises:
            NotInitializedException: If start() is called prior to initialize().
            AlreadyInitializedException: If start() is called when runtime is already running.
        """
        if not self._is_initialized:
            raise NotInitializedException("Cannot start RuntimeCoordinator: Infrastructure is not initialized. Call initialize() first.")
        if self._is_running:
            raise AlreadyInitializedException("RuntimeCoordinator is already running.")

        logger.info("Phase 2: Starting RuntimeCoordinator & executing startup recovery...")

        try:
            # Execute startup crash recovery (Section 5.14 & Section 12)
            recovery_summary = self.startup_recovery_service.execute_startup_recovery()

            self._is_running = True
            logger.info("Phase 2: RuntimeCoordinator started and operational.")
            return recovery_summary

        except Exception as e:
            logger.error(f"RuntimeCoordinator Phase 2 startup failed: {e}", exc_info=True)
            self.shutdown()
            raise RuntimeCoordinatorException(f"RuntimeCoordinator startup failed: {e}") from e

    def register_and_start_trade(
        self,
        trade_id: int,
        symbol: str,
        broker_account_id: int,
        manager_instance: Optional[OrderManagerService] = None
    ) -> OrderManagerService:
        """
        Phase 5 Live Trade Integration — Trade Open Lifecycle.

        Mandatory Order:
          1. Resolve BrokerAccount (validate parameters).
          2. Register OrderManager in OrderManagerRegistry FIRST (scoped by broker_account_id & symbol).
          3. Acquire AccountWebSocketFeed from AccountFeedManager.
          4. Connect feed if disconnected.
          5. Increment symbol reference count & subscribe broker only if ref_count 0 -> 1.

        Args:
            trade_id (int): Primary key ID of the active trade.
            symbol (str): Trading symbol.
            broker_account_id (int): Primary key ID of the BrokerAccount.
            manager_instance (Optional[OrderManagerService]): Existing OrderManagerService or None to instantiate.

        Returns:
            OrderManagerService: The registered OrderManagerService instance.
        """
        if not self._is_initialized or self.registry is None:
            raise NotInitializedException("Cannot register trade: RuntimeCoordinator is not initialized.")

        if not isinstance(broker_account_id, int) or broker_account_id <= 0:
            raise ValueError(f"Invalid broker_account_id: {broker_account_id}. Must be a positive integer.")

        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string.")

        symbol_upper = symbol.strip().upper()
        if manager_instance is None:
            manager_instance = self._create_manager_instance()

        # Step 1: Register in OrderManagerRegistry FIRST
        try:
            self.registry.register_trade(
                trade_id=trade_id,
                symbol=symbol_upper,
                manager_instance=manager_instance,
                broker_account_id=broker_account_id
            )
        except Exception as reg_err:
            logger.error(f"Failed to register trade {trade_id} in OrderManagerRegistry: {reg_err}")
            raise

        # Step 2: Acquire feed & subscribe symbol (if feed_manager is available)
        if self.feed_manager:
            try:
                feed = self.feed_manager.get_or_create_feed(
                    broker_account_id=broker_account_id,
                    on_tick_callback=self._handle_feed_tick
                )

                # Connect feed if required
                if not feed.is_connected():
                    feed.connect()

                # Increment reference count & subscribe symbol
                feed.subscribe_symbol(symbol_upper)

            except Exception as feed_err:
                logger.error(
                    f"Feed creation or subscription failed for Trade ID {trade_id} "
                    f"(BrokerAccount: {broker_account_id}, Symbol: '{symbol_upper}'): {feed_err}. Rolling back registration."
                )
                # Cleanup exception handling: Rollback registry entry if feed acquisition fails
                self.registry.unregister_trade(trade_id)
                raise RuntimeCoordinatorException(f"Live trade feed startup failed for trade {trade_id}: {feed_err}") from feed_err

        logger.info(
            f"Live Trade ID {trade_id} registered and feed started successfully "
            f"(BrokerAccount: {broker_account_id}, Symbol: '{symbol_upper}')."
        )
        return manager_instance

    def close_and_unregister_trade(self, trade_id: int) -> bool:
        """
        Phase 5 Live Trade Integration — Trade Closure Lifecycle.

        Mandatory Order:
          1. Resolve trade metadata (symbol, broker_account_id) from OrderManagerRegistry.
          2. Unregister OrderManager from OrderManagerRegistry FIRST.
          3. Decrement symbol reference count on AccountWebSocketFeed.
          4. Issue broker unsubscribe if symbol ref_count hits 0 (handled inside unsubscribe_symbol).
          5. If 0 active subscriptions remain on feed, disconnect feed and remove from AccountFeedManager.

        Args:
            trade_id (int): Primary key ID of the closing trade.

        Returns:
            bool: True if trade was found and unregistered, False otherwise.
        """
        if not self._is_initialized or self.registry is None:
            raise NotInitializedException("Cannot unregister trade: RuntimeCoordinator is not initialized.")

        info = self.registry.get_trade_info(trade_id)
        if not info:
            logger.warning(f"close_and_unregister_trade called for unregistered or already closed trade_id {trade_id}.")
            return False

        symbol = info.get("symbol")
        broker_account_id = info.get("broker_account_id")

        # Step 1: Unregister from OrderManagerRegistry FIRST
        unregistered = self.registry.unregister_trade(trade_id)

        # Step 2: Decrement symbol reference count & perform feed teardown
        if unregistered and self.feed_manager and broker_account_id and symbol:
            try:
                feed = self.feed_manager.get_feed(broker_account_id)
                if feed:
                    # Decrement reference count; auto-unsubscribes broker if ref_count hits 0
                    feed.unsubscribe_symbol(symbol)

                    # If no active subscriptions remain, disconnect feed and remove from registry
                    if len(feed.subscribed_symbols()) == 0:
                        logger.info(
                            f"AccountWebSocketFeed({broker_account_id}) has 0 active subscriptions. "
                            f"Disconnecting and removing from AccountFeedManager."
                        )
                        try:
                            if feed.is_connected():
                                feed.disconnect()
                        except Exception as disc_err:
                            logger.warning(f"Error disconnecting feed for broker_account_id {broker_account_id}: {disc_err}")
                        finally:
                            self.feed_manager.remove_feed(broker_account_id)

            except Exception as feed_err:
                logger.error(f"Error during feed cleanup for closed Trade ID {trade_id}: {feed_err}")

        logger.info(f"Live Trade ID {trade_id} closed and unregistered successfully.")
        return unregistered

    def _handle_feed_tick(
        self,
        broker_account_id: int,
        symbol: str,
        last_price: Any,
        tick_data: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Internal tick event handler bridging AccountWebSocketFeed -> TickRouter.
        """
        if self.tick_router:
            return self.tick_router.process_market_tick(
                broker_account_id=broker_account_id,
                symbol=symbol,
                last_price=last_price,
                tick_data=tick_data
            )
        return {"status": "SKIPPED", "reason": "TICK_ROUTER_NOT_INITIALIZED"}

    def _create_manager_instance(self) -> OrderManagerService:
        """
        Centralized factory callback producing initialized OrderManagerService instances.
        Passed to StartupRecoveryService and event routers.
        """
        return OrderManagerService(
            broker_factory=self.broker_factory,
            session_factory=self.session_factory
        )

    def shutdown(self) -> None:
        """
        Orchestrates graceful runtime shutdown by releasing feed handles and clearing registry state.
        """
        logger.info("Initiating RuntimeCoordinator shutdown sequence...")

        if self.feed_manager:
            try:
                self.feed_manager.clear(stop_all=True)
            except Exception as f_err:
                logger.warning(f"Error clearing feed_manager on shutdown: {f_err}")
            self.feed_manager = None

        if self.registry:
            self.registry.clear()
            self.registry = None

        self.startup_recovery_service = None
        self.broker_event_router = None
        self.tick_router = None
        self._is_initialized = False
        self._is_running = False
        logger.info("RuntimeCoordinator shutdown completed cleanly.")

    @property
    def is_initialized(self) -> bool:
        """Returns True if runtime infrastructure is constructed."""
        return self._is_initialized

    @property
    def is_running(self) -> bool:
        """Returns True if runtime has executed recovery and is operational."""
        return self._is_running

    def get_registry(self) -> OrderManagerRegistry:
        """
        Exposes controlled access to the OrderManagerRegistry.
        """
        if not self._is_initialized or self.registry is None:
            raise NotInitializedException("Cannot access registry: RuntimeCoordinator is not initialized.")
        return self.registry

    def get_feed_manager(self) -> AccountFeedManager:
        """
        Exposes controlled access to the AccountFeedManager.
        """
        if not self._is_initialized or self.feed_manager is None:
            raise NotInitializedException("Cannot access feed_manager: RuntimeCoordinator is not initialized.")
        return self.feed_manager

    def get_broker_event_router(self) -> BrokerEventRouter:
        """
        Exposes controlled access to the BrokerEventRouter.
        """
        if not self._is_initialized or self.broker_event_router is None:
            raise NotInitializedException("Cannot access broker_event_router: RuntimeCoordinator is not initialized.")
        return self.broker_event_router

    def get_tick_router(self) -> TickRouter:
        """
        Exposes controlled access to the TickRouter.
        """
        if not self._is_initialized or self.tick_router is None:
            raise NotInitializedException("Cannot access tick_router: RuntimeCoordinator is not initialized.")
        return self.tick_router

    def get_status(self) -> Dict[str, Any]:
        """
        Returns runtime health and status diagnostic metrics.
        """
        active_trades = self.registry._get_registered_trade_count() if self.registry else 0
        active_feeds = self.feed_manager.active_feed_count() if self.feed_manager else 0
        return {
            "is_initialized": self._is_initialized,
            "is_running": self._is_running,
            "active_trade_count": active_trades,
            "active_feed_count": active_feeds,
            "has_recovery_service": self.startup_recovery_service is not None,
            "has_broker_event_router": self.broker_event_router is not None,
            "has_tick_router": self.tick_router is not None
        }
