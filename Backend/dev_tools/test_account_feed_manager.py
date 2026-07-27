# e:/Internship/Backend/dev_tools/test_account_feed_manager.py
"""
Unit tests for AccountFeedManager (Phase 1 Validation).
Verifies:
  1. Registry creation & lookup by broker_account_id.
  2. Thread-safe lazy feed creation and double-check prevention under concurrency.
  3. Manual registration & duplicate protection.
  4. Controlled feed removal & teardown.
  5. API contracts (has_feed, get_feed, active_feed_count, clear).
"""

import threading
import unittest
from market_data.account_feed_manager import (
    AccountFeedManager,
    DuplicateFeedError,
    GenericAccountFeed
)


class DummyFeed:
    def __init__(self, broker_account_id: int):
        self.broker_account_id = broker_account_id
        self.stopped = False

    def disconnect(self):
        self.stopped = True


class TestAccountFeedManager(unittest.TestCase):

    def setUp(self):
        self.manager = AccountFeedManager()

    def tearDown(self):
        self.manager.clear(stop_all=True)

    def test_initial_state(self):
        """Verify new manager has 0 active feeds."""
        self.assertEqual(self.manager.active_feed_count(), 0)
        self.assertFalse(self.manager.has_feed(101))
        self.assertIsNone(self.manager.get_feed(101))

    def test_get_or_create_feed_lazy(self):
        """Verify lazy feed creation by broker_account_id."""
        feed1 = self.manager.get_or_create_feed(broker_account_id=101)
        self.assertIsNotNone(feed1)
        self.assertEqual(self.manager.active_feed_count(), 1)
        self.assertTrue(self.manager.has_feed(101))
        self.assertEqual(self.manager.get_feed(101), feed1)

    def test_duplicate_creation_returns_same_instance(self):
        """Verify calling get_or_create_feed multiple times returns exact same instance."""
        feed1 = self.manager.get_or_create_feed(broker_account_id=101)
        feed2 = self.manager.get_or_create_feed(broker_account_id=101)
        self.assertIs(feed1, feed2)
        self.assertEqual(self.manager.active_feed_count(), 1)

    def test_separate_accounts_get_separate_feeds(self):
        """Verify different broker_account_ids receive distinct feed instances."""
        feed1 = self.manager.get_or_create_feed(broker_account_id=101)
        feed2 = self.manager.get_or_create_feed(broker_account_id=102)
        self.assertIsNot(feed1, feed2)
        self.assertEqual(self.manager.active_feed_count(), 2)
        self.assertEqual(set(self.manager.get_all_active_broker_account_ids()), {101, 102})

    def test_manual_register_and_duplicate_error(self):
        """Verify manual registration and DuplicateFeedError when registering existing ID."""
        dummy = DummyFeed(broker_account_id=201)
        self.manager.register_feed(broker_account_id=201, feed_instance=dummy)
        self.assertTrue(self.manager.has_feed(201))
        self.assertEqual(self.manager.get_feed(201), dummy)

        with self.assertRaises(DuplicateFeedError):
            self.manager.register_feed(broker_account_id=201, feed_instance=dummy)

    def test_feed_removal(self):
        """Verify removing a feed triggers disconnect() and cleans registry."""
        dummy = DummyFeed(broker_account_id=301)
        self.manager.register_feed(broker_account_id=301, feed_instance=dummy)

        removed_feed = self.manager.remove_feed(broker_account_id=301, stop_feed=True)
        self.assertEqual(removed_feed, dummy)
        self.assertTrue(dummy.stopped)
        self.assertFalse(self.manager.has_feed(301))
        self.assertEqual(self.manager.active_feed_count(), 0)

    def test_invalid_broker_account_id_validation(self):
        """Verify invalid broker_account_id inputs raise ValueError."""
        with self.assertRaises(ValueError):
            self.manager.get_feed(0)

        with self.assertRaises(ValueError):
            self.manager.get_feed(-5)

        with self.assertRaises(ValueError):
            self.manager.get_or_create_feed("invalid")  # type: ignore

    def test_thread_safety_concurrent_creation(self):
        """Verify thread-safe creation: 20 concurrent threads requesting same ID yield 1 instance."""
        target_account_id = 999
        created_feeds = []

        def worker():
            feed = self.manager.get_or_create_feed(broker_account_id=target_account_id)
            created_feeds.append(feed)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(created_feeds), 20)
        # All returned instances must be identical
        first = created_feeds[0]
        for f in created_feeds:
            self.assertIs(f, first)
        self.assertEqual(self.manager.active_feed_count(), 1)


if __name__ == "__main__":
    unittest.main()
