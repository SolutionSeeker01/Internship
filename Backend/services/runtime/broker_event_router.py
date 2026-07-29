# Backend/services/runtime/broker_event_router.py
"""
Broker Event Router - Runtime Broker Callback & Event Routing Engine

Implements Stage 7B Step 2 of phase7_runtime_integration_plan.md and respects
Section 5.15 (Inputs & State Machine) of ARCHITECTURE_REFERENCE.md (v1.5.3).

Responsibilities:
  1. Part A: Accept raw broker callback events/DTOs.
  2. Part B: Resolve target order & trade_id via injected resolver or order/trade repositories.
  3. Part C: Resolve target OrderManagerService instance via OrderManagerRegistry.
  4. Part D: Dispatch the callback event to the resolved OrderManagerService.
  5. Part E: Gracefully handle unknown trades, missing managers, and stale callbacks.

Constraints:
  - NO trading business logic or state machine calculation rules.
  - NO tick routing or market data handling.
  - Infrastructure event router only.
"""

from typing import Dict, Any, Optional, Callable, Tuple
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database import order_repository, trade_repository
from services.runtime.order_manager_registry import OrderManagerRegistry
from utils.logger import get_logger

logger = get_logger(__name__)


class BrokerEventRouterException(Exception):
    """Base exception for BrokerEventRouter failures."""
    pass


class BrokerEventRouter:
    """
    Infrastructure router responsible for resolving target trades from broker callbacks
    and dispatching updates to active OrderManagerService instances.
    """

    def __init__(
        self,
        registry: OrderManagerRegistry,
        trade_resolver: Optional[Callable[[str, Session], Tuple[Optional[int], Optional[Any]]]] = None
    ):
        """
        Args:
            registry (OrderManagerRegistry): Thread-safe in-memory trade registry instance.
            trade_resolver (Optional[Callable[[str, Session], Tuple[Optional[int], Optional[Any]]]]):
                Optional injected strategy/resolver function that maps (broker_order_id, session) -> (trade_id, order_record).
                If omitted, defaults to repository resolution.
        """
        if registry is None:
            raise ValueError("registry is required for BrokerEventRouter.")
        self.registry = registry
        self.trade_resolver = trade_resolver or self._default_trade_resolver

    def _default_trade_resolver(
        self,
        broker_order_id: str,
        session: Session
    ) -> Tuple[Optional[int], Optional[Any]]:
        """
        Default repository resolution helper mapping broker_order_id -> (trade_id, order_record).
        """
        order_record = order_repository.get_order_by_broker_order_id(broker_order_id, session=session)
        if not order_record:
            return None, None

        trade_id = None
        if order_record.execution_target_id:
            trade = trade_repository.get_trade_by_execution_target_id(order_record.execution_target_id, session=session)
            if trade:
                trade_id = trade.id
        elif order_record.parent_order_id:
            parent_order = order_repository.get_order_by_id(order_record.parent_order_id, session=session)
            if parent_order and parent_order.execution_target_id:
                trade = trade_repository.get_trade_by_execution_target_id(parent_order.execution_target_id, session=session)
                if trade:
                    trade_id = trade.id

        return trade_id, order_record

    def process_broker_event(
        self,
        event_payload: Dict[str, Any],
        session: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Processes an incoming raw broker order update callback.

        Expected Payload Fields:
            - broker_order_id (str): Mandatory broker order identifier.
            - status (str): Updated status (COMPLETE, FILLED, CANCELLED, REJECTED, etc.).
            - filled_quantity (Optional[int]): Executed fill quantity.
            - average_price (Optional[float/Decimal]): Executed average price.

        Args:
            event_payload (Dict[str, Any]): Ingested broker callback payload dict.
            session (Optional[Session]): Optional database session.

        Returns:
            Dict[str, Any]: Processing outcome summary dict.
        """
        if not isinstance(event_payload, dict) or not event_payload:
            logger.warning("BrokerEventRouter received an empty or non-dict event payload.")
            return {"status": "SKIPPED", "reason": "EMPTY_PAYLOAD"}

        broker_order_id = event_payload.get("broker_order_id") or event_payload.get("order_id")
        if not broker_order_id or not isinstance(broker_order_id, str):
            logger.warning("BrokerEventRouter payload missing mandatory string 'broker_order_id' or 'order_id'.")
            return {"status": "SKIPPED", "reason": "MISSING_BROKER_ORDER_ID"}

        db = session if session else SessionLocal()
        own_session = session is None

        try:
            # 1. Resolve order_record and trade_id via injected/default trade_resolver
            trade_id, order_record = self.trade_resolver(broker_order_id, db)

            if not order_record:
                logger.warning(f"Broker callback ignored: No order record found for broker_order_id '{broker_order_id}'.")
                return {"status": "SKIPPED", "reason": "ORDER_RECORD_NOT_FOUND", "broker_order_id": broker_order_id}

            if not trade_id:
                logger.warning(f"Broker callback ignored: No trade record associated with broker_order_id '{broker_order_id}'.")
                return {"status": "SKIPPED", "reason": "TRADE_NOT_FOUND", "broker_order_id": broker_order_id}

            # 2. Resolve active manager from OrderManagerRegistry
            manager = self.registry.get_manager_by_trade_id(trade_id)
            if not manager:
                logger.info(
                    f"Broker callback ignored: Trade ID {trade_id} is not registered in active OrderManagerRegistry "
                    f"(Trade may already be CLOSED or un-restored)."
                )
                return {"status": "SKIPPED", "reason": "MANAGER_NOT_REGISTERED", "trade_id": trade_id}

            # 3. Dispatch event update to the target OrderManagerService
            from dev_tools.drm import global_event_bus, RuntimeEvent
            global_event_bus.publish(RuntimeEvent(
                event_type="BROKER_CALLBACK_RECEIVED",
                component="BROKER_EVENT_ROUTER",
                trade_id=trade_id,
                order_id=broker_order_id,
                payload={"status": event_payload.get("status"), "broker_order_id": broker_order_id}
            ))

            logger.info(f"Dispatching broker callback for order '{broker_order_id}' to OrderManager for trade ID {trade_id}...")
            
            # Delegate callback handling to order manager
            dispatch_status = "DISPATCHED"
            try:
                if hasattr(manager, "process_broker_order_update"):
                    # Normalize the payload: forward using 'order_id' key which matches
                    # what KiteTicker sends and what process_broker_order_update expects.
                    normalized_payload = dict(event_payload)
                    normalized_payload.setdefault("order_id", broker_order_id)
                    manager.process_broker_order_update(normalized_payload)
                else:
                    logger.warning(f"OrderManagerService for trade {trade_id} has no process_broker_order_update method — cannot dispatch broker event.")
                    dispatch_status = "DISPATCH_SKIPPED_NO_HANDLER"

                global_event_bus.publish(RuntimeEvent(
                    event_type="BROKER_CALLBACK_DISPATCHED",
                    component="BROKER_EVENT_ROUTER",
                    trade_id=trade_id,
                    order_id=broker_order_id,
                    payload={"result": dispatch_status}
                ))
            except Exception as dispatch_err:
                logger.error(f"Error during manager callback dispatch for Trade ID {trade_id}: {dispatch_err}", exc_info=True)
                dispatch_status = "DISPATCH_ERROR"

            logger.info(f"Broker event for broker_order_id '{broker_order_id}' dispatched to Trade ID {trade_id}.")
            return {
                "status": dispatch_status,
                "trade_id": trade_id,
                "broker_order_id": broker_order_id,
                "order_role": getattr(order_record, "order_role", "UNKNOWN")
            }

        finally:
            if own_session:
                db.close()
