# e:/Internship/Backend/dev_tools/test_account_websocket_feed.py
"""
Unit test suite for Phase 2 AccountWebSocketFeed & BaseBrokerFeed interface.
Verifies:
  1. Initial state & lightweight construction (DISCONNECTED, no auto-connect).
  2. State machine transitions & invalid transition rejection.
  3. Reference-counted subscription logic (0 -> 1 subscribe, 1 -> 2 count only).
  4. Reference-counted unsubscription logic (2 -> 1 count only, 1 -> 0 unsubscribe).
  5. Dynamic auto-teardown when active subscriptions drop to 0.
  6. Reconnection hook & batched subscription restoration.
  7. Multi-threaded concurrent subscribe / unsubscribe safety under lock.
  8. AccountFeedManager integration with concrete AccountWebSocketFeed type hints.
"""

import threading
import unittest
from market_data.base_feed import FeedState, InvalidFeedStateTransitionError
from market_data.account_websocket_feed import AccountWebSocketFeed
from market_data.account_feed_manager import AccountFeedManager


class TestAccountWebSocketFeed(unittest.TestCase):

    def setUp(self):
        self.feed = AccountWebSocketFeed(
            broker_account_id=101,
            broker_name="ZERODHA",
            auto_disconnect_on_zero_subs=True
        )

    def tearDown(self):
        if self.feed.current_state() != FeedState.DISCONNECTED:
            self.feed.disconnect()

    def test_initial_state(self):
        """Verify lightweight initialization defaults to DISCONNECTED with 0 active subs."""
        self.assertEqual(self.feed.broker_account_id, 101)
        self.assertEqual(self.feed.broker_name, "ZERODHA")
        self.assertEqual(self.feed.current_state(), FeedState.DISCONNECTED)
        self.assertFalse(self.feed.is_connected())
        self.assertEqual(len(self.feed.subscribed_symbols()), 0)

    def test_successful_connect_and_disconnect(self):
        """Verify valid state transitions: DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTING -> DISCONNECTED."""
        self.feed.connect()
        self.assertEqual(self.feed.current_state(), FeedState.CONNECTED)
        self.assertTrue(self.feed.is_connected())

        self.feed.disconnect()
        self.assertEqual(self.feed.current_state(), FeedState.DISCONNECTED)
        self.assertFalse(self.feed.is_connected())

    def test_invalid_state_transitions_rejected(self):
        """Verify forbidden state machine transitions throw InvalidFeedStateTransitionError."""
        # DISCONNECTED -> DISCONNECTING (Forbidden)
        with self.assertRaises(InvalidFeedStateTransitionError):
            self.feed._transition_to(FeedState.DISCONNECTING)

        # Connect to reach CONNECTED
        self.feed.connect()
        self.assertEqual(self.feed.current_state(), FeedState.CONNECTED)

        # CONNECTED -> CONNECTING is valid for reconnect, but DISCONNECTED directly from CONNECTED without DISCONNECTING is invalid
        with self.assertRaises(InvalidFeedStateTransitionError):
            self.feed._transition_to(FeedState.DISCONNECTED)

    def test_reference_counted_subscriptions_single_symbol(self):
        """Verify 0 -> 1 triggers broker sub, 1 -> 2 increments count only."""
        # First sub (RELIANCE)
        issued_broker_sub_1 = self.feed.subscribe_symbol("RELIANCE", token=738561)
        self.assertTrue(issued_broker_sub_1)
        self.assertEqual(self.feed.reference_count("RELIANCE"), 1)
        self.assertEqual(self.feed.subscribed_symbols(), ["RELIANCE"])
        self.assertTrue(self.feed.is_connected())  # Lazy connected

        # Second sub (RELIANCE)
        issued_broker_sub_2 = self.feed.subscribe_symbol("RELIANCE", token=738561)
        self.assertFalse(issued_broker_sub_2)  # Count incremented only
        self.assertEqual(self.feed.reference_count("RELIANCE"), 2)
        self.assertEqual(self.feed.subscribed_symbols(), ["RELIANCE"])

    def test_reference_counted_unsubscriptions_single_symbol(self):
        """Verify 2 -> 1 decrements count, 1 -> 0 triggers broker unsub and auto-teardown."""
        self.feed.subscribe_symbol("RELIANCE", token=738561)
        self.feed.subscribe_symbol("RELIANCE", token=738561)
        self.assertEqual(self.feed.reference_count("RELIANCE"), 2)

        # First unsub (2 -> 1)
        issued_broker_unsub_1 = self.feed.unsubscribe_symbol("RELIANCE")
        self.assertFalse(issued_broker_unsub_1)  # Count decremented only
        self.assertEqual(self.feed.reference_count("RELIANCE"), 1)
        self.assertTrue(self.feed.is_connected())

        # Second unsub (1 -> 0)
        issued_broker_unsub_2 = self.feed.unsubscribe_symbol("RELIANCE")
        self.assertTrue(issued_broker_unsub_2)  # Unsub issued
        self.assertEqual(self.feed.reference_count("RELIANCE"), 0)
        self.assertEqual(len(self.feed.subscribed_symbols()), 0)
        self.assertEqual(self.feed.current_state(), FeedState.DISCONNECTED)  # Auto-disconnected

    def test_multiple_symbols_handling(self):
        """Verify independent reference counting across multiple symbols."""
        self.feed.subscribe_symbol("RELIANCE")
        self.feed.subscribe_symbol("BHARTIARTL")

        self.assertEqual(set(self.feed.subscribed_symbols()), {"RELIANCE", "BHARTIARTL"})
        self.assertEqual(self.feed.reference_count("RELIANCE"), 1)
        self.assertEqual(self.feed.reference_count("BHARTIARTL"), 1)

        # Unsub RELIANCE -> BHARTIARTL remains active, feed stays CONNECTED
        self.feed.unsubscribe_symbol("RELIANCE")
        self.assertEqual(self.feed.subscribed_symbols(), ["BHARTIARTL"])
        self.assertTrue(self.feed.is_connected())

        # Unsub BHARTIARTL -> 0 active subs -> Feed auto-disconnects
        self.feed.unsubscribe_symbol("BHARTIARTL")
        self.assertEqual(len(self.feed.subscribed_symbols()), 0)
        self.assertEqual(self.feed.current_state(), FeedState.DISCONNECTED)

    def test_reconnect_flow(self):
        """Verify reconnect flow preserves active reference counts and re-subscribes."""
        self.feed.subscribe_symbol("RELIANCE")
        self.feed.subscribe_symbol("INFY")

        self.feed.reconnect()
        self.assertTrue(self.feed.is_connected())
        self.assertEqual(set(self.feed.subscribed_symbols()), {"RELIANCE", "INFY"})
        self.assertEqual(self.feed.reference_count("RELIANCE"), 1)
        self.assertEqual(self.feed.reference_count("INFY"), 1)

    def test_concurrent_subscribe_unsubscribe_thread_safety(self):
        """Verify 20 concurrent threads subscribing and unsubscribing maintain zero count corruption."""
        symbol = "TATASTEEL"

        def worker_subscribe():
            self.feed.subscribe_symbol(symbol)

        def worker_unsubscribe():
            self.feed.unsubscribe_symbol(symbol)

        # 10 sub threads + 10 unsub threads
        sub_threads = [threading.Thread(target=worker_subscribe) for _ in range(10)]
        for t in sub_threads:
            t.start()
        for t in sub_threads:
            t.join()

        self.assertEqual(self.feed.reference_count(symbol), 10)

        unsub_threads = [threading.Thread(target=worker_unsubscribe) for _ in range(10)]
        for t in unsub_threads:
            t.start()
        for t in unsub_threads:
            t.join()

        self.assertEqual(self.feed.reference_count(symbol), 0)
        self.assertFalse(self.feed.is_connected())

    def test_account_feed_manager_integration(self):
        """Verify AccountFeedManager instantiates and returns typed AccountWebSocketFeed instances."""
        manager = AccountFeedManager()
        feed = manager.get_or_create_feed(broker_account_id=202)

        self.assertIsInstance(feed, AccountWebSocketFeed)
        self.assertEqual(feed.broker_account_id, 202)
        self.assertEqual(manager.active_feed_count(), 1)
        manager.clear(stop_all=True)


if __name__ == "__main__":
    unittest.main()
