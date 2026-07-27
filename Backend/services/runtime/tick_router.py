# Backend/services/runtime/tick_router.py
"""
Tick Router - Runtime Market Tick Distribution Router

Implements Stage 7B Step 3 of phase7_runtime_integration_plan.md and respects
Section 5.15 (Inputs & Subsection 5) of ARCHITECTURE_REFERENCE.md (v1.5.3).

Responsibilities:
  1. Part A: Accept incoming live market tick LTP events.
  2. Part B: Resolve all active trade IDs for symbol via OrderManagerRegistry.
  3. Part C: Resolve active OrderManagerService instances and dispatch tick.
  4. Part D: Gracefully handle unknown symbols, missing managers, and dispatch errors.

Constraints:
  - NO trading business logic, TP/SL checks, or trailing stop calculations.
  - NO database persistence or repository calls.
  - NO broker interface calls.
  - Infrastructure tick distribution router only.
"""

from decimal import Decimal
from typing import Dict, Any, List, Optional
from services.runtime.order_manager_registry import OrderManagerRegistry
from utils.logger import get_logger

logger = get_logger(__name__)


class TickRouterException(Exception):
    """Base exception for TickRouter failures."""
    pass


class TickRouter:
    """
    High-throughput non-blocking router responsible for resolving active trades
    by symbol and dispatching live LTP tick updates to target OrderManagerService instances.
    """

    def __init__(self, registry: OrderManagerRegistry):
        """
        Args:
            registry (OrderManagerRegistry): Thread-safe in-memory trade registry instance.
        """
        if registry is None:
            raise ValueError("registry is required for TickRouter.")
        self.registry = registry

    def process_market_tick(
        self,
        broker_account_id: Optional[int],
        symbol: str,
        last_price: Any,
        tick_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Processes an incoming live market tick event.

        Canonical Manager Callback Contract:
            - Calls manager.process_market_tick(trade_id=trade_id, current_ltp=current_ltp)

        Args:
            broker_account_id (Optional[int]): Mandatory BrokerAccount primary key ID for client isolation.
            symbol (str): Mandatory trading symbol (e.g. 'RELIANCE', 'SBIN').
            last_price (Any): Mandatory last traded price (Decimal, float, int, or str).
            tick_data (Optional[Dict[str, Any]]): Optional complete tick dictionary payload.

        Returns:
            Dict[str, Any]: Routing summary dictionary preserving exact Decimal price precision.
        """
        if not symbol or not isinstance(symbol, str):
            logger.warning("TickRouter received tick with invalid or missing symbol.")
            return {"status": "SKIPPED", "reason": "INVALID_SYMBOL"}

        if last_price is None:
            logger.warning(f"TickRouter received tick for '{symbol}' with missing last_price.")
            return {"status": "SKIPPED", "reason": "MISSING_LAST_PRICE"}

        try:
            current_ltp = Decimal(str(last_price))
            if current_ltp <= Decimal("0"):
                logger.warning(f"TickRouter received tick for '{symbol}' with non-positive price: {last_price}")
                return {"status": "SKIPPED", "reason": "INVALID_PRICE"}
        except Exception:
            logger.warning(f"TickRouter failed to convert last_price '{last_price}' to Decimal for symbol '{symbol}'.")
            return {"status": "SKIPPED", "reason": "INVALID_PRICE_FORMAT"}

        symbol_upper = symbol.strip().upper()

        # 1. Resolve active trade IDs from OrderManagerRegistry using (broker_account_id, symbol)
        if isinstance(broker_account_id, int) and broker_account_id > 0:
            trade_ids: List[int] = self.registry.get_active_trade_ids_for_broker_and_symbol(
                broker_account_id=broker_account_id,
                symbol=symbol_upper
            )
        else:
            # Fallback to global symbol index for legacy calls
            trade_ids = self.registry.get_active_trade_ids_for_symbol(symbol_upper)

        if not trade_ids:
            logger.debug(f"TickRouter: No active trades registered for (BrokerAccount: {broker_account_id}, Symbol: '{symbol_upper}').")
            return {
                "status": "SKIPPED",
                "reason": "NO_ACTIVE_TRADES",
                "broker_account_id": broker_account_id,
                "symbol": symbol_upper
            }

        dispatched_count = 0
        failed_count = 0
        missing_managers = 0

        # 2. Dispatch tick to each active OrderManagerService instance via canonical process_market_tick contract
        for trade_id in trade_ids:
            manager = self.registry.get_manager_by_trade_id(trade_id)
            if not manager:
                missing_managers += 1
                logger.warning(f"TickRouter: Trade ID {trade_id} listed for symbol '{symbol_upper}' but manager missing in registry.")
                continue

            try:
                # Canonical OrderManagerService callback contract
                if hasattr(manager, "process_market_tick"):
                    manager.process_market_tick(trade_id=trade_id, current_ltp=current_ltp)
                dispatched_count += 1
            except Exception as dispatch_err:
                failed_count += 1
                logger.error(f"Error dispatching tick '{symbol_upper}' to Trade ID {trade_id}: {dispatch_err}", exc_info=True)

        logger.debug(
            f"TickRouter routed '{symbol_upper}' @ {current_ltp} to {dispatched_count} trade(s) "
            f"(Failed: {failed_count}, Missing: {missing_managers})."
        )
        return {
            "status": "ROUTED",
            "symbol": symbol_upper,
            "current_ltp": current_ltp,
            "dispatched_count": dispatched_count,
            "failed_count": failed_count,
            "missing_managers": missing_managers
        }
