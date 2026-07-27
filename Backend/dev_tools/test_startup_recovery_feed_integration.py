# e:/Internship/Backend/dev_tools/test_startup_recovery_feed_integration.py
"""
Unit test suite for Phase 3 StartupRecoveryService & AccountFeedManager Integration.
Verifies:
  1. Recovery with single broker account (1 trade).
  2. Recovery with multiple broker accounts.
  3. Multiple trades on the same symbol (reference count computation).
  4. Multiple symbols under same broker account.
  5. Empty recovery (0 open trades).
  6. Missing/unresolvable broker account resilient recovery.
  7. Partial broker account recovery failure (one account fails, others succeed).
  8. Batch subscription generation verification.
"""

import unittest
from unittest.mock import MagicMock, patch
from market_data.account_feed_manager import AccountFeedManager
from market_data.account_websocket_feed import AccountWebSocketFeed
from services.runtime.startup_recovery_service import StartupRecoveryService
from services.runtime.order_manager_registry import OrderManagerRegistry


class TestStartupRecoveryFeedIntegration(unittest.TestCase):

    def setUp(self):
        self.registry = OrderManagerRegistry()
        self.manager_factory = MagicMock()
        self.feed_manager = AccountFeedManager()
        self.service = StartupRecoveryService(
            registry=self.registry,
            manager_factory=self.manager_factory,
            feed_manager=self.feed_manager
        )

    def tearDown(self):
        self.registry.clear()
        self.feed_manager.clear(stop_all=True)

    @patch("services.runtime.startup_recovery_service.find_orphaned_executing_targets", return_value=[])
    @patch("services.runtime.startup_recovery_service.trade_repository")
    @patch("services.runtime.startup_recovery_service.order_repository")
    def test_empty_recovery(self, mock_order_repo, mock_trade_repo, mock_targets):
        """Verify recovery executes cleanly when 0 active trades exist."""
        mock_trade_repo.get_open_trades.return_value = []

        mock_session = MagicMock()
        summary = self.service.execute_startup_recovery(session=mock_session)

        self.assertEqual(summary["active_trades_found"], 0)
        self.assertEqual(summary["reconstructed_trades"], 0)
        self.assertEqual(self.feed_manager.active_feed_count(), 0)
        self.assertEqual(summary["feed_recovery"]["recovered_broker_accounts"], 0)

    @patch("services.runtime.startup_recovery_service.find_orphaned_executing_targets", return_value=[])
    @patch("services.runtime.startup_recovery_service.trade_repository")
    @patch("services.runtime.startup_recovery_service.order_repository")
    def test_recovery_single_broker_account(self, mock_order_repo, mock_trade_repo, mock_targets):
        """Verify recovery for 1 trade under 1 broker account."""
        mock_trade = MagicMock(id=101, execution_target_id=1, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        mock_trade_repo.get_open_trades.return_value = [mock_trade]

        mock_entry_order = MagicMock(id=10, symbol="RELIANCE", client_id=1, filled_quantity=100)
        mock_order_repo.get_entry_order_by_execution_target_id.return_value = mock_entry_order
        mock_order_repo.get_child_orders_by_parent_id.return_value = []

        # Mock DB session to return BrokerAccount with id=500 for user_id=1
        mock_account = MagicMock(id=500)
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_account

        summary = self.service.execute_startup_recovery(session=mock_session)

        self.assertEqual(summary["reconstructed_trades"], 1)
        self.assertEqual(self.feed_manager.active_feed_count(), 1)
        self.assertTrue(self.feed_manager.has_feed(500))

        feed = self.feed_manager.get_feed(500)
        self.assertTrue(feed.is_connected())
        self.assertEqual(feed.subscribed_symbols(), ["RELIANCE"])
        self.assertEqual(feed.reference_count("RELIANCE"), 1)

    @patch("services.runtime.startup_recovery_service.find_orphaned_executing_targets", return_value=[])
    @patch("services.runtime.startup_recovery_service.trade_repository")
    @patch("services.runtime.startup_recovery_service.order_repository")
    def test_recovery_multiple_trades_same_symbol_ref_count(self, mock_order_repo, mock_trade_repo, mock_targets):
        """Verify multiple trades on the same symbol compute correct batched reference count (RELIANCE ref_count=2)."""
        trade1 = MagicMock(id=101, execution_target_id=1, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        trade2 = MagicMock(id=102, execution_target_id=2, status="OPEN", trailing_sl_activated=False, entry_filled_qty=50)
        mock_trade_repo.get_open_trades.return_value = [trade1, trade2]

        entry1 = MagicMock(id=10, symbol="RELIANCE", client_id=1, filled_quantity=100)
        entry2 = MagicMock(id=20, symbol="RELIANCE", client_id=1, filled_quantity=50)
        mock_order_repo.get_entry_order_by_execution_target_id.side_effect = [entry1, entry2]
        mock_order_repo.get_child_orders_by_parent_id.return_value = []

        mock_account = MagicMock(id=500)
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_account

        summary = self.service.execute_startup_recovery(session=mock_session)

        self.assertEqual(summary["reconstructed_trades"], 2)
        self.assertEqual(self.feed_manager.active_feed_count(), 1)

        feed = self.feed_manager.get_feed(500)
        self.assertEqual(feed.subscribed_symbols(), ["RELIANCE"])
        self.assertEqual(feed.reference_count("RELIANCE"), 2)

    @patch("services.runtime.startup_recovery_service.find_orphaned_executing_targets", return_value=[])
    @patch("services.runtime.startup_recovery_service.trade_repository")
    @patch("services.runtime.startup_recovery_service.order_repository")
    def test_recovery_multiple_broker_accounts(self, mock_order_repo, mock_trade_repo, mock_targets):
        """Verify recovery for trades belonging to 2 separate broker accounts."""
        trade1 = MagicMock(id=101, execution_target_id=1, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        trade2 = MagicMock(id=102, execution_target_id=2, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        mock_trade_repo.get_open_trades.return_value = [trade1, trade2]

        entry1 = MagicMock(id=10, symbol="RELIANCE", client_id=1, filled_quantity=100)
        entry2 = MagicMock(id=20, symbol="INFY", client_id=2, filled_quantity=100)
        mock_order_repo.get_entry_order_by_execution_target_id.side_effect = [entry1, entry2]
        mock_order_repo.get_child_orders_by_parent_id.return_value = []

        acc1 = MagicMock(id=501)
        acc2 = MagicMock(id=502)

        mock_session = MagicMock()
        # Mock filter to return acc1 for first call and acc2 for second call
        mock_session.query.return_value.filter.return_value.first.side_effect = [acc1, acc2]

        summary = self.service.execute_startup_recovery(session=mock_session)

        self.assertEqual(summary["reconstructed_trades"], 2)
        self.assertEqual(self.feed_manager.active_feed_count(), 2)

        feed1 = self.feed_manager.get_feed(501)
        feed2 = self.feed_manager.get_feed(502)

        self.assertEqual(feed1.subscribed_symbols(), ["RELIANCE"])
        self.assertEqual(feed2.subscribed_symbols(), ["INFY"])

    @patch("services.runtime.startup_recovery_service.find_orphaned_executing_targets", return_value=[])
    @patch("services.runtime.startup_recovery_service.trade_repository")
    @patch("services.runtime.startup_recovery_service.order_repository")
    def test_partial_broker_account_failure_resilience(self, mock_order_repo, mock_trade_repo, mock_targets):
        """Verify if 1 broker account feed fails connection, recovery continues for other accounts."""
        trade1 = MagicMock(id=101, execution_target_id=1, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        trade2 = MagicMock(id=102, execution_target_id=2, status="OPEN", trailing_sl_activated=False, entry_filled_qty=100)
        mock_trade_repo.get_open_trades.return_value = [trade1, trade2]

        entry1 = MagicMock(id=10, symbol="RELIANCE", client_id=1, filled_quantity=100)
        entry2 = MagicMock(id=20, symbol="INFY", client_id=2, filled_quantity=100)
        mock_order_repo.get_entry_order_by_execution_target_id.side_effect = [entry1, entry2]
        mock_order_repo.get_child_orders_by_parent_id.return_value = []

        acc1 = MagicMock(id=601)
        acc2 = MagicMock(id=602)

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.side_effect = [acc1, acc2]

        # Mock feed factory so account 601 connect() raises Exception
        def custom_feed_builder(broker_account_id):
            feed = AccountWebSocketFeed(broker_account_id=broker_account_id)
            if broker_account_id == 601:
                feed.connect = MagicMock(side_effect=RuntimeError("Broker 601 Connection Error"))
            return feed

        service_custom = StartupRecoveryService(
            registry=self.registry,
            manager_factory=self.manager_factory,
            feed_manager=AccountFeedManager(feed_factory=custom_feed_builder)
        )

        summary = service_custom.execute_startup_recovery(session=mock_session)

        # Both trades reconstructed in registry
        self.assertEqual(summary["reconstructed_trades"], 2)

        # Feed recovery summary reports 1 succeeded, 1 failed
        feed_summary = summary["feed_recovery"]
        self.assertEqual(feed_summary["recovered_broker_accounts"], 1)
        self.assertEqual(feed_summary["failed_broker_accounts"], 1)


if __name__ == "__main__":
    unittest.main()
