# Backend/dev_tools/drm/publisher.py
"""
Runtime Event Publisher Helper — Lightweight Event Emission Utility

Provides a single, clean helper function `emit_event` for backend components
to publish RuntimeEvents without constructing boilerplate objects or inline imports.

Constraints:
  - Zero business logic
  - Zero event state tracking
  - Pure passive event forwarding
"""

from typing import Dict, Any, Optional
from dev_tools.drm.models import RuntimeEvent
from dev_tools.drm.event_bus import global_event_bus


def emit_event(
    event_type: str,
    component: str,
    execution_target_id: Optional[int] = None,
    trade_id: Optional[int] = None,
    broker_order_id: Optional[str] = None,
    severity: str = "INFO",
    payload: Optional[Dict[str, Any]] = None
) -> None:
    """
    Constructs and publishes a RuntimeEvent onto the global_event_bus.

    Args:
        event_type (str): Unique event classification (e.g. "SIGNAL_RECEIVED", "RISK_CHECK_PASSED").
        component (str): Originating backend component (e.g. "TRADE_ENGINE", "ORDER_MGR").
        execution_target_id (Optional[int]): Execution target primary key ID.
        trade_id (Optional[int]): Trade primary key ID.
        broker_order_id (Optional[str]): Broker order ID string.
        severity (str): "INFO", "WARNING", or "ERROR".
        payload (Optional[Dict[str, Any]]): Contextual event data dictionary.
    """
    event_data = payload.copy() if payload else {}
    if execution_target_id is not None:
        event_data["execution_target_id"] = execution_target_id
    if trade_id is not None:
        event_data["trade_id"] = trade_id
    if broker_order_id is not None:
        event_data["broker_order_id"] = broker_order_id

    event = RuntimeEvent(
        event_type=event_type,
        component=component,
        trade_id=trade_id,
        order_id=broker_order_id,
        severity=severity,
        payload=event_data
    )
    global_event_bus.publish(event)
