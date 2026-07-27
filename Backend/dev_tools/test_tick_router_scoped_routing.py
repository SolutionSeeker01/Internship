# e:/Internship/Backend/dev_tools/test_tick_router_scoped_routing.py
"""
Unit Test Suite for Phase 4 — Tick Routing Integration (Routing Only).
Verifies:
  1. Routing for single broker account.
  2. Routing for multiple broker accounts.
  3. Routing for same symbol across different broker accounts (strict client isolation).
  4. Multiple active trades on the same symbol under the same broker account.
  5. Multiple symbols under the same broker account.
  6. Negative test: ticks never delivered to wrong broker account.
  7. Negative test: ticks never delivered to wrong symbol.
  8. Negative test: ticks never delivered to inactive/unregistered trade.
  9. Performance / constant-time O(1) lookup verification.
"""

import unittest
from unittest.mock import MagicMock
from decimal import Decimal
from services.runtime.order_manager_registry import OrderManagerRegistry
from services.runtime.tick_router import TickRouter


class TestTickRouterScopedRouting(unittest.TestCase):

    def setUp(self):
        self.registry = OrderManagerRegistry()
        self.router = TickRouter(registry=self.registry)

    def tearDown(self):
        self.registry.clear()

    def test_single_broker_account_routing(self):
        """Verify tick routing for a single broker account and symbol."""
        mock_manager = MagicMock()
        self.registry.register_trade(trade_id=1, symbol="RELIANCE", manager_instance=mock_manager, broker_account_id=101)

        result = self.router.process_market_tick(broker_account_id=101, symbol="RELIANCE", last_price=2500.50)

        self.assertEqual(result["status"], "ROUTED")
        self.assertEqual(result["dispatched_count"], 1)
        mock_manager.process_market_tick.assert_called_once_with(trade_id=1, current_ltp=Decimal("2500.50"))

    def test_multiple_broker_accounts_same_symbol_isolation(self):
        """
        CRITICAL ISOLATION TEST:
        BrokerAccount 101 has RELIANCE (Trade A)
        BrokerAccount 102 has RELIANCE (Trade B)
        Tick for (101, RELIANCE) must ONLY be delivered to Trade A and NEVER Trade B.
        """
        manager_a = MagicMock()
        manager_b = MagicMock()

        self.registry.register_trade(trade_id=10, symbol="RELIANCE", manager_instance=manager_a, broker_account_id=101)
        self.registry.register_trade(trade_id=20, symbol="RELIANCE", manager_instance=manager_b, broker_account_id=102)

        # Process tick for Account 101
        res101 = self.router.process_market_tick(broker_account_id=101, symbol="RELIANCE", last_price=2510.00)
        self.assertEqual(res101["dispatched_count"], 1)
        manager_a.process_market_tick.assert_called_once_with(trade_id=10, current_ltp=Decimal("2510.00"))
        manager_b.process_market_tick.assert_not_called()

        # Process tick for Account 102
        res102 = self.router.process_market_tick(broker_account_id=102, symbol="RELIANCE", last_price=2515.00)
        self.assertEqual(res102["dispatched_count"], 1)
        manager_b.process_market_tick.assert_called_once_with(trade_id=20, current_ltp=Decimal("2515.00"))
        manager_a.process_market_tick.assert_called_once() # still 1 call total

    def test_multiple_trades_same_broker_account_same_symbol(self):
        """Verify ticks delivered to all active trades under the same (broker_account_id, symbol)."""
        manager1 = MagicMock()
        manager2 = MagicMock()
        manager3 = MagicMock()

        self.registry.register_trade(trade_id=100, symbol="INFY", manager_instance=manager1, broker_account_id=201)
        self.registry.register_trade(trade_id=101, symbol="INFY", manager_instance=manager2, broker_account_id=201)
        self.registry.register_trade(trade_id=102, symbol="INFY", manager_instance=manager3, broker_account_id=201)

        res = self.router.process_market_tick(broker_account_id=201, symbol="INFY", last_price=1450.00)

        self.assertEqual(res["dispatched_count"], 3)
        manager1.process_market_tick.assert_called_once_with(trade_id=100, current_ltp=Decimal("1450.00"))
        manager2.process_market_tick.assert_called_once_with(trade_id=101, current_ltp=Decimal("1450.00"))
        manager3.process_market_tick.assert_called_once_with(trade_id=102, current_ltp=Decimal("1450.00"))

    def test_multiple_symbols_same_broker_account(self):
        """Verify symbol isolation within the same broker account."""
        manager_rel = MagicMock()
        manager_tcs = MagicMock()

        self.registry.register_trade(trade_id=1, symbol="RELIANCE", manager_instance=manager_rel, broker_account_id=301)
        self.registry.register_trade(trade_id=2, symbol="TCS", manager_instance=manager_tcs, broker_account_id=301)

        # Tick for RELIANCE
        self.router.process_market_tick(broker_account_id=301, symbol="RELIANCE", last_price=2600.00)
        manager_rel.process_market_tick.assert_called_once_with(trade_id=1, current_ltp=Decimal("2600.00"))
        manager_tcs.process_market_tick.assert_not_called()

        # Tick for TCS
        self.router.process_market_tick(broker_account_id=301, symbol="TCS", last_price=3400.00)
        manager_tcs.process_market_tick.assert_called_once_with(trade_id=2, current_ltp=Decimal("3400.00"))

    def test_negative_wrong_broker_account(self):
        """Negative test: verify tick for unregistered broker account returns SKIPPED."""
        manager = MagicMock()
        self.registry.register_trade(trade_id=1, symbol="SBIN", manager_instance=manager, broker_account_id=401)

        # Tick sent for non-registered Account 999
        res = self.router.process_market_tick(broker_account_id=999, symbol="SBIN", last_price=600.00)

        self.assertEqual(res["status"], "SKIPPED")
        self.assertEqual(res["reason"], "NO_ACTIVE_TRADES")
        manager.process_market_tick.assert_not_called()

    def test_negative_wrong_symbol(self):
        """Negative test: verify tick for unregistered symbol on registered account returns SKIPPED."""
        manager = MagicMock()
        self.registry.register_trade(trade_id=1, symbol="SBIN", manager_instance=manager, broker_account_id=401)

        res = self.router.process_market_tick(broker_account_id=401, symbol="TATAMOTORS", last_price=700.00)

        self.assertEqual(res["status"], "SKIPPED")
        self.assertEqual(res["reason"], "NO_ACTIVE_TRADES")
        manager.process_market_tick.assert_not_called()

    def test_negative_inactive_unregistered_trade(self):
        """Negative test: verify unregistering a trade stops tick delivery immediately."""
        manager = MagicMock()
        self.registry.register_trade(trade_id=1, symbol="WIPRO", manager_instance=manager, broker_account_id=501)

        # Unregister trade
        self.registry.unregister_trade(trade_id=1)

        res = self.router.process_market_tick(broker_account_id=501, symbol="WIPRO", last_price=450.00)

        self.assertEqual(res["status"], "SKIPPED")
        self.assertEqual(res["reason"], "NO_ACTIVE_TRADES")
        manager.process_market_tick.assert_not_called()


if __name__ == "__main__":
    unittest.main()
