# Backend/dev_tools/console/state.py
"""
Console State Store — Thread-Safe In-Memory Telemetry State Manager

Passively consumes RuntimeEvents from global_event_bus and maintains lightweight
structured data for console rendering. Strictly read-only; zero domain side-effects.
"""

import threading
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional
from dev_tools.drm.models import RuntimeEvent


# Standard 11 Stage Pipeline definition for timeline rendering
STAGES = [
    ("SIGNAL_RECEIVED", "Stage 1: Signal Received"),
    ("SIGNAL_VALIDATED", "Stage 2: Signal Validated"),
    ("ELIGIBILITY_COMPLETED", "Stage 3: Target Eligibility Evaluated"),
    ("EXECUTION_STARTED", "Stage 4: Pipeline Execution Started"),
    ("RUNTIME_VALIDATION_PASSED", "Stage 5: Runtime Validation Passed"),
    ("RISK_CHECK_PASSED", "Stage 6: Risk Budget Approved"),
    ("QUANTITY_CALCULATED", "Stage 7: Share Quantity Sized"),
    ("ORDER_SPEC_CREATED", "Stage 8: Broker OrderSpec Created"),
    ("ENTRY_SUBMITTED", "Stage 9: Entry Order Submitted"),
    ("SAFETY_SL_PLACED", "Stage 10: Position Protected (SL Placed)"),
    ("TRADE_COMPLETED", "Stage 11: Trade Execution Completed")
]


class ConsoleState:
    """
    Thread-safe store holding in-memory data for DVC rendering.
    """

    def __init__(self, max_recent_logs: int = 8, max_exceptions: int = 5):
        self._lock = threading.Lock()
        self.start_time = datetime.now()
        self.total_events = 0
        self.last_event_time: Optional[datetime] = None

        # Active trade state maps execution_target_id -> dict details
        self.active_trade: Optional[Dict[str, Any]] = None
        self.waiting_state: str = "WAITING FOR SIGNAL INGESTION"

        # Persistent timeline stages status: stage_key -> {status: 'PENDING'|'RUNNING'|'COMPLETED'|'FAILED', timestamp: str, detail: str}
        self.timeline: Dict[str, Dict[str, Any]] = {
            stage_key: {"status": "PENDING", "timestamp": "", "detail": "", "label": label}
            for stage_key, label in STAGES
        }

        # Rolling recent events log
        self.recent_logs: deque = deque(maxlen=max_recent_logs)

        # Exception history buffer
        self.exceptions: deque = deque(maxlen=max_exceptions)

    def on_event(self, event: RuntimeEvent) -> None:
        """
        Passive subscriber callback invoked by RuntimeEventBus worker thread.
        Must complete fast (< 0.05ms) under lock.
        """
        with self._lock:
            self.total_events += 1
            self.last_event_time = event.timestamp
            ts_str = event.timestamp.strftime("%H:%M:%S.%f")[:-3]

            # 1. Append to recent rolling logs
            self.recent_logs.appendleft({
                "timestamp": ts_str,
                "event_type": event.event_type,
                "component": event.component,
                "severity": event.severity,
                "payload": event.payload
            })

            # 2. Record Error/Exception if applicable
            if event.severity == "ERROR" or "FAILED" in event.event_type or "REJECTED" in event.event_type:
                self.exceptions.appendleft({
                    "timestamp": ts_str,
                    "event_type": event.event_type,
                    "component": event.component,
                    "reason": event.payload.get("fail_reason", "Execution Rejected")
                })
                self.waiting_state = f"❌ HALTED AT {event.event_type}: {event.payload.get('fail_reason', 'Error')}"

            # 3. Update Active Trade Header & Waiting State
            self._update_trade_and_timeline(event, ts_str)

    def _update_trade_and_timeline(self, event: RuntimeEvent, ts_str: str) -> None:
        """Updates internal timeline and trade metrics based on event type."""
        e_type = event.event_type
        payload = event.payload

        # Initialize or update active trade structure
        if e_type == "SIGNAL_RECEIVED":
            self.active_trade = {
                "symbol": payload.get("symbol", "N/A"),
                "action": payload.get("action", "N/A"),
                "entry": payload.get("entry", 0.0),
                "sl": payload.get("sl", 0.0),
                "quantity": 0,
                "status": "SIGNAL_RECEIVED",
                "broker_order_id": "-"
            }
            self.waiting_state = "WAITING FOR SIGNAL VALIDATION"
            # Reset timeline for fresh signal
            for stage_key, label in STAGES:
                self.timeline[stage_key] = {"status": "PENDING", "timestamp": "", "detail": "", "label": label}
            self.timeline["SIGNAL_RECEIVED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Source: {payload.get('source')}", "label": "Stage 1: Signal Received"}

        elif e_type == "SIGNAL_VALIDATED":
            self.waiting_state = "WAITING FOR ELIGIBILITY EVALUATION"
            self.timeline["SIGNAL_VALIDATED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Status: {payload.get('validation_status')}", "label": "Stage 2: Signal Validated"}

        elif e_type == "ELIGIBILITY_COMPLETED":
            self.waiting_state = "WAITING FOR PIPELINE EXECUTION"
            self.timeline["ELIGIBILITY_COMPLETED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Ready targets: {payload.get('ready')}", "label": "Stage 3: Target Eligibility Evaluated"}

        elif e_type == "EXECUTION_STARTED":
            if not self.active_trade:
                self.active_trade = {
                    "symbol": payload.get("symbol", "N/A"),
                    "action": payload.get("action", "N/A"),
                    "entry": 0.0,
                    "sl": 0.0,
                    "quantity": 0,
                    "status": "EXECUTION_STARTED",
                    "broker_order_id": "-"
                }
            else:
                self.active_trade["status"] = "EXECUTION_STARTED"
                if payload.get("symbol"):
                    self.active_trade["symbol"] = payload.get("symbol")
                if payload.get("action"):
                    self.active_trade["action"] = payload.get("action")
            self.active_trade["target_id"] = payload.get("execution_target_id")
            self.waiting_state = "WAITING FOR RUNTIME VALIDATION"
            self.timeline["EXECUTION_STARTED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Target ID #{payload.get('execution_target_id')}", "label": "Stage 4: Pipeline Execution Started"}

        elif e_type == "RUNTIME_VALIDATION_PASSED":
            if self.active_trade:
                self.active_trade["status"] = "RUNTIME_VALIDATION_PASSED"
            self.waiting_state = "WAITING FOR RISK MANAGER"
            self.timeline["RUNTIME_VALIDATION_PASSED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": "Sanity checks passed", "label": "Stage 5: Runtime Validation Passed"}

        elif e_type == "RUNTIME_VALIDATION_FAILED":
            if self.active_trade:
                self.active_trade["status"] = "RUNTIME_VALIDATION_FAILED"
            self.timeline["RUNTIME_VALIDATION_PASSED"] = {"status": "FAILED", "timestamp": ts_str, "detail": payload.get("fail_reason", ""), "label": "Stage 5: Runtime Validation Failed"}

        elif e_type == "RISK_CHECK_PASSED":
            if self.active_trade:
                self.active_trade["status"] = "RISK_CHECK_PASSED"
            self.waiting_state = "WAITING FOR QUANTITY CALCULATOR"
            self.timeline["RISK_CHECK_PASSED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Max Risk: ₹{payload.get('max_risk', 0):.2f}", "label": "Stage 6: Risk Budget Approved"}

        elif e_type == "RISK_CHECK_FAILED":
            if self.active_trade:
                self.active_trade["status"] = "RISK_CHECK_FAILED"
            self.timeline["RISK_CHECK_PASSED"] = {"status": "FAILED", "timestamp": ts_str, "detail": payload.get("fail_reason", ""), "label": "Stage 6: Risk Budget Rejected"}

        elif e_type == "QUANTITY_CALCULATED":
            if self.active_trade:
                self.active_trade["quantity"] = payload.get("quantity", 0)
            self.waiting_state = "WAITING FOR ORDER BUILDER"
            self.timeline["QUANTITY_CALCULATED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Sized Qty: {payload.get('quantity')} shares", "label": "Stage 7: Share Quantity Sized"}

        elif e_type == "QUANTITY_CALC_FAILED":
            self.timeline["QUANTITY_CALCULATED"] = {"status": "FAILED", "timestamp": ts_str, "detail": payload.get("fail_reason", ""), "label": "Stage 7: Quantity Calculation Failed"}

        elif e_type == "ORDER_SPEC_CREATED":
            self.waiting_state = "WAITING FOR BROKER DISPATCH"
            self.timeline["ORDER_SPEC_CREATED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Price: ₹{payload.get('price', 0):.2f}", "label": "Stage 8: Broker OrderSpec Created"}

        elif e_type == "ENTRY_SUBMITTED":
            b_id = payload.get("broker_order_id", "-")
            if self.active_trade:
                self.active_trade["broker_order_id"] = b_id
                self.active_trade["status"] = "ENTRY_SUBMITTED"
            self.waiting_state = "WAITING FOR BROKER FILL & SL PLACEMENT"
            self.timeline["ENTRY_SUBMITTED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"Order ID: {b_id}", "label": "Stage 9: Entry Order Submitted"}

        elif e_type == "SAFETY_SL_PLACED":
            self.waiting_state = "WAITING FOR TARGET OR SL TRIGGER (POSITION PROTECTED)"
            self.timeline["SAFETY_SL_PLACED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": f"SL Order: {payload.get('broker_order_id')}", "label": "Stage 10: Position Protected (SL Placed)"}

        elif e_type == "TRADE_COMPLETED":
            if self.active_trade:
                self.active_trade["status"] = "CLOSED"
            self.waiting_state = "TRADE COMPLETED — ALL TARGETS / EXITS EXECUTED"
            self.timeline["TRADE_COMPLETED"] = {"status": "COMPLETED", "timestamp": ts_str, "detail": "Position Closed", "label": "Stage 11: Trade Execution Completed"}

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns thread-safe snapshot copy of state for rendering."""
        with self._lock:
            uptime = int((datetime.now() - self.start_time).total_seconds())
            return {
                "uptime": f"{uptime // 60}m {uptime % 60}s",
                "total_events": self.total_events,
                "waiting_state": self.waiting_state,
                "active_trade": self.active_trade.copy() if self.active_trade else None,
                "timeline": [dict(v) for v in self.timeline.values()],
                "recent_logs": list(self.recent_logs),
                "exceptions": list(self.exceptions)
            }
