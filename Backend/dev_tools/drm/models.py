# Backend/dev_tools/drm/models.py
"""
Runtime Event Model — Passive Telemetry DTO

Represents a single atomic event emitted by backend pipeline stages for monitoring and validation.
Strictly decoupled from trading domain models, database schemas, and broker logic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class RuntimeEvent:
    """
    Immutable DTO for telemetry events.

    Fields:
        event_type (str): Unique event classification (e.g. "SIGNAL_RECEIVED", "RISK_PASSED").
        component (str): Originating backend component (e.g. "TRADE_ENGINE", "ORDER_MGR").
        trade_id (Optional[int]): Associated Trade ID (if applicable).
        order_id (Optional[str]): Broker order ID or internal order ID (if applicable).
        severity (str): "INFO", "WARNING", or "ERROR". Defaults to "INFO".
        payload (Dict[str, Any]): Additional non-sensitive contextual payload.
        timestamp (datetime): Event generation timestamp.
    """
    event_type: str
    component: str
    trade_id: Optional[int] = None
    order_id: Optional[str] = None
    severity: str = "INFO"
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Converts RuntimeEvent to standard dictionary representation."""
        return {
            "event_type": self.event_type,
            "component": self.component,
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload
        }
