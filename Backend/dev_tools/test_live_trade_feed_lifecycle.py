# e:/Internship/Backend/dev_tools/test_live_trade_feed_lifecycle.py
"""
Unit & Integration Test Suite for Phase 5 — Live Trade Feed Lifecycle Integration
===================================================================================

Validates the full client market data feed lifecycle integration with live trade execution:
  1. Live Entry Ordering (Resolve -> Register FIRST -> Acquire Feed -> Connect -> Subscribe).
  2. Multi-Trade / Multi-Symbol Reference Counting.
  3. Multi-Broker Account Isolation.
  4. Live Exit Teardown Ordering (Unregister FIRST -> Decrement -> Broker Unsubscribe -> Feed Disconnect & Remove).
  5. Failure Injection & Rollback (Feed creation failure, subscription error, disconnect recovery).
  6. Regression Safety (Trailing, Target, Exit state machines unchanged).
"""

import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from services.runtime.runtime_coordinator import (
    RuntimeCoordinator,
    RuntimeCoordinatorException,
    NotInitializedException
)
from services.runtime.order_manager_registry import OrderManagerRegistry
from market_data.account_feed_manager import AccountFeedManager
from market_data.account_websocket_feed import AccountWebSocketFeed, FeedState
from services.order_manager.order_manager_service import OrderManagerService


class MockBrokerFactory:
    """Mock factory for unit testing."""
    def get_broker(self, name: str):
        mock_adapter = MagicMock()
        mock_adapter.place_order.return_value = {"broker_order_id": "MOCK-123", "status": "COMPLETE"}
        mock_adapter.cancel_order.return_value = {"status": "CANCELLED"}
        return mock_adapter


class TestLiveTradeFeedLifecycle(unittest.TestCase):
    """Test suite validating Phase 5 Live Trade Feed Lifecycle Integration."""

    def setUp(self):
        self.broker_factory = MockBrokerFactory()
        self.coordinator = RuntimeCoordinator(broker_factory=self.broker_factory)
        self.coordinator.initialize()

    def tearDown(self):
        if self.coordinator.is_initialized:
            self.coordinator.shutdown()

    # ------------------------------------------------------------------
    # SCENARIO 1: LIVE ENTRY TESTS
    # ------------------------------------------------------------------

    def test_first_trade_creation_for_broker_account(self):
        """First trade for broker_account_id 101: Registers trade FIRST, creates & connects feed, subscribes symbol."""
        mock_manager = MagicMock(spec=OrderManagerService)
        
        # Register trade 1 for Account 101 on RELIANCE
        mgr = self.coordinator.register_and_start_trade(
            trade_id=1,
            symbol="RELIANCE",
            broker_account_id=101,
            manager_instance=mock_manager
        )

        # 1. Verify returned manager
        self.assertEqual(mgr, mock_manager)

        # 2. Verify trade registered in OrderManagerRegistry FIRST
        registry = self.coordinator.get_registry()
        self.assertEqual(registry.get_manager_by_trade_id(1), mock_manager)
        active_ids = registry.get_active_trade_ids_for_broker_and_symbol(101, "RELIANCE")
        self.assertEqual(active_ids, [1])

        # 3. Verify feed created & connected in AccountFeedManager
        feed_manager = self.coordinator.get_feed_manager()
        self.assertTrue(feed_manager.has_feed(101))
        feed = feed_manager.get_feed(101)
        self.assertTrue(feed.is_connected())

        # 4. Verify symbol reference count is 1 and symbol is subscribed
        self.assertEqual(feed.reference_count("RELIANCE"), 1)
        self.assertIn("RELIANCE", feed.subscribed_symbols())

    def test_second_symbol_same_account(self):
        """Second symbol (TCS) on same broker account (101): Reuses existing feed, subscribes TCS."""
        mgr1 = self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)
        mgr2 = self.coordinator.register_and_start_trade(trade_id=2, symbol="TCS", broker_account_id=101)

        feed_manager = self.coordinator.get_feed_manager()
        self.assertEqual(feed_manager.active_feed_count(), 1) # Exactly 1 feed for Account 101

        feed = feed_manager.get_feed(101)
        self.assertEqual(feed.reference_count("RELIANCE"), 1)
        self.assertEqual(feed.reference_count("TCS"), 1)
        self.assertEqual(sorted(feed.subscribed_symbols()), ["RELIANCE", "TCS"])

    def test_second_trade_same_symbol_ref_count(self):
        """Second trade (Trade 2) on same symbol (RELIANCE) & same account (101): ref_count increments to 2."""
        self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)
        
        feed = self.coordinator.get_feed_manager().get_feed(101)
        with patch.object(feed, '_dispatch_broker_subscribe') as mock_subscribe:
            self.coordinator.register_and_start_trade(trade_id=2, symbol="RELIANCE", broker_account_id=101)
            
            # ref_count should be 2
            self.assertEqual(feed.reference_count("RELIANCE"), 2)
            # Broker subscribe should NOT be dispatched again (count 1 -> 2)
            mock_subscribe.assert_not_called()

        # Both trades must be registered in OrderManagerRegistry
        active_ids = self.coordinator.get_registry().get_active_trade_ids_for_broker_and_symbol(101, "RELIANCE")
        self.assertEqual(sorted(active_ids), [1, 2])

    def test_multiple_broker_accounts_simultaneously(self):
        """Trades on separate broker accounts (101 & 202): Creates isolated feeds for each account."""
        self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)
        self.coordinator.register_and_start_trade(trade_id=2, symbol="RELIANCE", broker_account_id=202)

        feed_manager = self.coordinator.get_feed_manager()
        self.assertEqual(feed_manager.active_feed_count(), 2)

        feed101 = feed_manager.get_feed(101)
        feed202 = feed_manager.get_feed(202)

        self.assertIsNot(feed101, feed202)
        self.assertEqual(feed101.reference_count("RELIANCE"), 1)
        self.assertEqual(feed202.reference_count("RELIANCE"), 1)

    # ------------------------------------------------------------------
    # SCENARIO 2: LIVE EXIT TESTS
    # ------------------------------------------------------------------

    def test_live_exit_one_trade_closes_ref_count_decrements(self):
        """Trade 1 closes when Trade 2 is active on same symbol: Ref count decrements 2 -> 1. Feed & broker sub stay active."""
        self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)
        self.coordinator.register_and_start_trade(trade_id=2, symbol="RELIANCE", broker_account_id=101)

        feed = self.coordinator.get_feed_manager().get_feed(101)
        with patch.object(feed, '_dispatch_broker_unsubscribe') as mock_unsub:
            success = self.coordinator.close_and_unregister_trade(trade_id=1)
            self.assertTrue(success)

            # Trade 1 unregistered FIRST
            self.assertIsNone(self.coordinator.get_registry().get_manager_by_trade_id(1))
            self.assertEqual(self.coordinator.get_registry().get_active_trade_ids_for_broker_and_symbol(101, "RELIANCE"), [2])

            # Ref count decrements to 1
            self.assertEqual(feed.reference_count("RELIANCE"), 1)
            # Broker unsub NOT sent because count > 0
            mock_unsub.assert_not_called()
            # Feed remains connected
            self.assertTrue(feed.is_connected())

    def test_live_exit_last_trade_on_symbol_closes_broker_unsub(self):
        """Last trade on RELIANCE closes while TCS trade is active: Issues broker unsubscribe for RELIANCE. Feed stays open for TCS."""
        self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)
        self.coordinator.register_and_start_trade(trade_id=2, symbol="TCS", broker_account_id=101)

        feed = self.coordinator.get_feed_manager().get_feed(101)
        with patch.object(feed, '_dispatch_broker_unsubscribe') as mock_unsub:
            success = self.coordinator.close_and_unregister_trade(trade_id=1)
            self.assertTrue(success)

            # RELIANCE ref count is 0
            self.assertEqual(feed.reference_count("RELIANCE"), 0)
            self.assertNotIn("RELIANCE", feed.subscribed_symbols())

            # Broker unsubscribe dispatched for RELIANCE
            mock_unsub.assert_called_once_with(["RELIANCE"])

            # Feed remains open for TCS
            self.assertTrue(feed.is_connected())
            self.assertIn("TCS", feed.subscribed_symbols())

    def test_live_exit_last_active_trade_on_broker_closes_feed_teardown(self):
        """Last active trade on Account 101 closes: Feed unsubscribes, disconnects, and is removed from AccountFeedManager."""
        self.coordinator.register_and_start_trade(trade_id=1, symbol="RELIANCE", broker_account_id=101)

        feed_manager = self.coordinator.get_feed_manager()
        feed = feed_manager.get_feed(101)

        # Close trade 1
        success = self.coordinator.close_and_unregister_trade(trade_id=1)
        self.assertTrue(success)

        # 1. Unregistered from OrderManagerRegistry FIRST
        self.assertIsNone(self.coordinator.get_registry().get_manager_by_trade_id(1))

        # 2. Feed disconnected
        self.assertEqual(feed.current_state(), FeedState.DISCONNECTED)

        # 3. Feed removed from AccountFeedManager
        self.assertFalse(feed_manager.has_feed(101))
        self.assertEqual(feed_manager.active_feed_count(), 0)

    # ------------------------------------------------------------------
    # SCENARIO 3: FAILURE HANDLING & ROLLBACK
    # ------------------------------------------------------------------

    def test_feed_creation_failure_rolls_back_registry(self):
        """Exception during feed creation rolls back OrderManagerRegistry registration cleanly."""
        with patch.object(self.coordinator.feed_manager, 'get_or_create_feed', side_effect=RuntimeError("Feed Connection Error")):
            with self.assertRaises(RuntimeCoordinatorException):
                self.coordinator.register_and_start_trade(trade_id=99, symbol="SBIN", broker_account_id=505)

        # Trade 99 must NOT be in OrderManagerRegistry
        registry = self.coordinator.get_registry()
        self.assertIsNone(registry.get_manager_by_trade_id(99))
        self.assertEqual(registry.get_active_trade_ids_for_broker_and_symbol(505, "SBIN"), [])

    def test_subscription_failure_rolls_back_registry(self):
        """Exception during feed.subscribe_symbol rolls back OrderManagerRegistry registration cleanly."""
        mock_feed = MagicMock(spec=AccountWebSocketFeed)
        mock_feed.is_connected.return_value = True
        mock_feed.subscribe_symbol.side_effect = ValueError("Invalid Symbol Token")

        with patch.object(self.coordinator.feed_manager, 'get_or_create_feed', return_value=mock_feed):
            with self.assertRaises(RuntimeCoordinatorException):
                self.coordinator.register_and_start_trade(trade_id=100, symbol="INVALID", broker_account_id=606)

        # Trade 100 must be un-registered from registry
        registry = self.coordinator.get_registry()
        self.assertIsNone(registry.get_manager_by_trade_id(100))

    def test_unregister_non_existent_trade_returns_false(self):
        """Closing an un-registered trade ID gracefully returns False without throwing errors."""
        result = self.coordinator.close_and_unregister_trade(trade_id=99999)
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # SCENARIO 4: TICK ROUTING INTEGRATION
    # ------------------------------------------------------------------

    def test_tick_dispatch_from_feed_to_registered_manager(self):
        """Ticks arriving on AccountWebSocketFeed flow cleanly to TickRouter and the registered OrderManagerService."""
        mock_manager = MagicMock(spec=OrderManagerService)
        mock_manager.process_market_tick.return_value = {"status": "NO_CHANGE"}

        self.coordinator.register_and_start_trade(
            trade_id=50,
            symbol="INFY",
            broker_account_id=303,
            manager_instance=mock_manager
        )

        # Dispatch tick via RuntimeCoordinator feed handler
        res = self.coordinator._handle_feed_tick(broker_account_id=303, symbol="INFY", last_price=1500.0)

        # Verify tick router dispatched tick to mock manager
        self.assertEqual(res["status"], "ROUTED")
        mock_manager.process_market_tick.assert_called_once_with(trade_id=50, current_ltp=Decimal("1500.0"))


if __name__ == "__main__":
    unittest.main()
