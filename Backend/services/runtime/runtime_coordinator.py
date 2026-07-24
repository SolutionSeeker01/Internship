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
    event routing, tick routing, and shutdown lifecycle for the backend trading platform.
    """

    def __init__(
        self,
        broker_factory: Any,
        session_factory: Optional[Callable[[], Any]] = None,
        subscription_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Args:
            broker_factory (Any): Central BrokerFactory instance for manager creation.
            session_factory (Optional[Callable[[], Any]]): DB Session factory (defaults to SessionLocal).
            subscription_callback (Optional[Callable[[str], None]]): Optional callback function for market data subscriptions.
        """
        if broker_factory is None:
            raise ValueError("broker_factory is required for RuntimeCoordinator.")

        self.broker_factory = broker_factory
        self.session_factory = session_factory or SessionLocal
        self.subscription_callback = subscription_callback

        self.registry: Optional[OrderManagerRegistry] = None
        self.startup_recovery_service: Optional[StartupRecoveryService] = None
        self.broker_event_router: Optional[BrokerEventRouter] = None
        self.tick_router: Optional[TickRouter] = None
        
        self._is_initialized: bool = False
        self._is_running: bool = False

    def initialize(self) -> None:
        """
        Phase 1 — Infrastructure Construction & Dependency Composition.

        Instantiates runtime registry, recovery service, broker event router, and tick router,
        wiring all internal dependencies. No recovery execution occurs during this phase.

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

            # 2. Instantiate StartupRecoveryService injecting manager_factory callback
            self.startup_recovery_service = StartupRecoveryService(
                registry=self.registry,
                manager_factory=self._create_manager_instance,
                subscription_callback=self.subscription_callback
            )

            # 3. Instantiate BrokerEventRouter
            self.broker_event_router = BrokerEventRouter(registry=self.registry)

            # 4. Instantiate TickRouter
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
        Orchestrates graceful runtime shutdown by releasing resources and clearing registry state.
        """
        logger.info("Initiating RuntimeCoordinator shutdown sequence...")
        
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
        return {
            "is_initialized": self._is_initialized,
            "is_running": self._is_running,
            "active_trade_count": active_trades,
            "has_recovery_service": self.startup_recovery_service is not None,
            "has_broker_event_router": self.broker_event_router is not None,
            "has_tick_router": self.tick_router is not None
        }
