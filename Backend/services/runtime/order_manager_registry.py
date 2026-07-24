# Backend/services/runtime/order_manager_registry.py
"""
Order Manager Registry - In-Memory Runtime Trade Manager Registry

Implements Stage 7A Step 1 of phase7_runtime_integration_plan.md and respects
Principle P2 (Thin Coordinator Pattern) and Principle P10 (Client Execution Isolation)
from ARCHITECTURE_REFERENCE.md (v1.5.3).

Responsibilities:
  1. Register an active OrderManagerService instance when a trade becomes active.
  2. Unregister an OrderManagerService instance when a trade reaches CLOSED status.
  3. Resolve active manager instances by trade ID (O(1)).
  4. Resolve active trade IDs by symbol for tick routing (O(1)).
  5. Support safe concurrent access across background worker threads and tasks.

Constraints:
  - NO business rules or trading calculations.
  - NO database persistence or repository calls.
  - NO broker interface calls.
  - NO state machine transition logic.
  - Infrastructure-only in-memory registry.
"""

import threading
from typing import Dict, Set, Optional, List, TYPE_CHECKING
from exceptions import ValidationException
from utils.logger import get_logger

if TYPE_CHECKING:
    from services.order_manager.order_manager_service import OrderManagerService

logger = get_logger(__name__)


class DuplicateTradeRegistrationException(ValidationException):
    """Raised when an attempt is made to register an already registered active trade_id."""
    pass


class OrderManagerRegistry:
    """
    Thread-safe in-memory registry maintaining active OrderManagerService instances
    and reverse symbol indexes for high-performance tick routing.
    """

    def __init__(self):
        """
        Initializes empty in-memory maps and a re-entrant lock (RLock) for safe concurrency.
        """
        self._lock = threading.RLock()
        
        # Primary map: trade_id -> (manager_instance, symbol)
        self._trade_map: Dict[int, Dict[str, Any]] = {}
        
        # Reverse index: symbol -> Set of active trade_ids
        self._symbol_index: Dict[str, Set[int]] = {}

    def register_trade(
        self,
        trade_id: int,
        symbol: str,
        manager_instance: "OrderManagerService"
    ) -> None:
        """
        Registers an active trade and its OrderManagerService instance in the registry.

        Args:
            trade_id (int): Primary key ID of the trade.
            symbol (str): Trading symbol (e.g. 'RELIANCE', 'SBIN').
            manager_instance (OrderManagerService): Instantiated OrderManagerService instance.

        Raises:
            ValueError: If inputs are invalid (e.g. trade_id <= 0, empty symbol, missing manager).
            DuplicateTradeRegistrationException: If trade_id is already registered.
        """
        if not isinstance(trade_id, int) or trade_id <= 0:
            raise ValueError(f"Invalid trade_id '{trade_id}': must be a positive integer.")
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"Invalid symbol '{symbol}': must be a non-empty string.")
        if manager_instance is None:
            raise ValueError("manager_instance is required and cannot be None.")

        symbol_upper = symbol.strip().upper()

        with self._lock:
            if trade_id in self._trade_map:
                logger.error(f"Invariant Violation: Trade ID {trade_id} is already registered in OrderManagerRegistry.")
                raise DuplicateTradeRegistrationException(
                    f"Trade ID {trade_id} is already registered in OrderManagerRegistry."
                )

            # 1. Register in primary trade map (minimal state: manager, symbol)
            self._trade_map[trade_id] = {
                "manager": manager_instance,
                "symbol": symbol_upper
            }

            # 2. Add to reverse symbol index
            if symbol_upper not in self._symbol_index:
                self._symbol_index[symbol_upper] = set()
            self._symbol_index[symbol_upper].add(trade_id)

            logger.debug(f"Registered Trade ID {trade_id} (Symbol: '{symbol_upper}') in OrderManagerRegistry.")

    def unregister_trade(self, trade_id: int) -> bool:
        """
        Unregisters an active trade and cleans up its symbol index entry upon trade closure.

        Args:
            trade_id (int): Primary key ID of the trade to unregister.

        Returns:
            bool: True if trade was found and unregistered, False if trade_id was not registered.
        """
        with self._lock:
            if trade_id not in self._trade_map:
                logger.debug(f"Attempted to unregister unknown Trade ID {trade_id}.")
                return False

            trade_entry = self._trade_map.pop(trade_id)
            symbol_upper = trade_entry["symbol"]

            # Clean up reverse symbol index
            if symbol_upper in self._symbol_index:
                self._symbol_index[symbol_upper].discard(trade_id)
                # Automatically prune symbol key if no active trades remain for this symbol
                if not self._symbol_index[symbol_upper]:
                    del self._symbol_index[symbol_upper]

            logger.debug(f"Unregistered Trade ID {trade_id} (Symbol: '{symbol_upper}') from OrderManagerRegistry.")
            return True

    def get_manager_by_trade_id(self, trade_id: int) -> Optional["OrderManagerService"]:
        """
        Resolves an active OrderManagerService instance by trade ID in O(1) time.

        Args:
            trade_id (int): Primary key ID of the trade.

        Returns:
            Optional[OrderManagerService]: The active OrderManagerService instance, or None if not registered.
        """
        with self._lock:
            entry = self._trade_map.get(trade_id)
            return entry["manager"] if entry else None

    def get_active_trade_ids_for_symbol(self, symbol: str) -> List[int]:
        """
        Resolves a list of active trade IDs subscribed to a trading symbol in O(1) time.

        Returns a thread-safe snapshot list of trade IDs. Modifying the returned list 
        does NOT affect the internal registry index.

        Args:
            symbol (str): Trading symbol.

        Returns:
            List[int]: Snapshot list of active trade IDs matching the symbol.
        """
        if not symbol or not isinstance(symbol, str):
            return []

        symbol_upper = symbol.strip().upper()

        with self._lock:
            trade_ids = self._symbol_index.get(symbol_upper, set())
            return list(trade_ids)

    def is_symbol_subscribed(self, symbol: str) -> bool:
        """
        Checks whether at least one active trade is subscribed to a trading symbol.

        Args:
            symbol (str): Trading symbol.

        Returns:
            bool: True if symbol has 1 or more active registered trades, False otherwise.
        """
        if not symbol or not isinstance(symbol, str):
            return False

        symbol_upper = symbol.strip().upper()

        with self._lock:
            return symbol_upper in self._symbol_index and len(self._symbol_index[symbol_upper]) > 0

    def _get_registered_trade_count(self) -> int:
        """
        Internal diagnostic helper returning total active trade count.
        """
        with self._lock:
            return len(self._trade_map)

    def clear(self) -> None:
        """
        Clears all registered trades and symbol indexes (used during shutdown or testing).
        """
        with self._lock:
            self._trade_map.clear()
            self._symbol_index.clear()
            logger.debug("OrderManagerRegistry cleared completely.")
