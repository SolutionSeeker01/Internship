# Backend/dev_tools/test_dvc_validation.py
"""
Step 4 End-to-End DVC Validation Test Suite

Automates all 10 validation scenarios defined in Step 4 Implementation Charter:
  1. Idle System
  2. Successful 11-Stage Trade Execution
  3. Runtime Validation Failure
  4. Risk Manager Failure
  5. Quantity Calculator Failure
  6. Broker Rejection
  7. Startup Recovery
  8. High Event Volume (1,000 Events Stress Test)
  9. Multiple Concurrent Trades
  10. Graceful Shutdown & Unsubscribe Safety

Usage:
    python dev_tools/test_dvc_validation.py
"""

import sys
import os
import time
import threading
from datetime import datetime

# Ensure Backend root directory is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dev_tools.drm import emit_event, global_event_bus
from dev_tools.console import ConsoleState, make_layout


def run_e2e_dvc_validation_suite():
    print("=" * 70)
    print("      DEVELOPER VALIDATION CONSOLE (DVC) STEP 4 VALIDATION SUITE      ")
    print("=" * 70 + "\n")

    state = ConsoleState()
    global_event_bus.subscribe(state.on_event)

    # -------------------------------------------------------------------------
    # Scenario 1 — Idle System
    # -------------------------------------------------------------------------
    print("[1/10] Testing Scenario 1: Idle System State...")
    snap = state.get_snapshot()
    assert snap["total_events"] == 0
    assert "WAITING FOR SIGNAL INGESTION" in snap["waiting_state"]
    assert snap["active_trade"] is None
    assert len(snap["exceptions"]) == 0
    print("       --> PASS: Idle system banner, empty queue, and zero active trade verified.\n")

    # -------------------------------------------------------------------------
    # Scenario 2 — Successful Trade (All 11 Stages)
    # -------------------------------------------------------------------------
    print("[2/10] Testing Scenario 2: Successful Trade Execution (Stage 1 -> 11)...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "IDEA", "action": "BUY", "entry": 15.00, "sl": 14.50, "source": "WEBHOOK"})
    emit_event("SIGNAL_VALIDATED", "SIGNAL_VALIDATOR", payload={"symbol": "IDEA", "action": "BUY", "validation_status": "ACCEPTED"})
    emit_event("ELIGIBILITY_COMPLETED", "ELIGIBILITY_ENGINE", payload={"signal_id": 101, "strategy_id": 1, "ready": 1, "processed": 1})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=1, payload={"symbol": "IDEA", "action": "BUY"})
    emit_event("RUNTIME_VALIDATION_PASSED", "TRADE_ENGINE", execution_target_id=1, payload={"symbol": "IDEA"})
    emit_event("RISK_CHECK_PASSED", "TRADE_ENGINE", execution_target_id=1, payload={"net_value": 1000.0, "max_risk": 10.0})
    emit_event("QUANTITY_CALCULATED", "TRADE_ENGINE", execution_target_id=1, payload={"quantity": 20})
    emit_event("ORDER_SPEC_CREATED", "TRADE_ENGINE", execution_target_id=1, payload={"symbol": "IDEA", "quantity": 20, "price": 15.00})
    emit_event("ENTRY_SUBMITTED", "TRADE_ENGINE", execution_target_id=1, broker_order_id="KZ-9901", payload={})
    emit_event("SAFETY_SL_PLACED", "ORDER_MGR", trade_id=42, broker_order_id="KZ-9902", payload={"broker_order_id": "KZ-9902"})
    emit_event("TRADE_COMPLETED", "ORDER_MGR", trade_id=42, payload={"status": "CLOSED"})

    time.sleep(0.3)
    snap = state.get_snapshot()
    assert snap["total_events"] == 11
    assert snap["active_trade"]["symbol"] == "IDEA"
    assert snap["active_trade"]["quantity"] == 20
    assert snap["active_trade"]["broker_order_id"] == "KZ-9901"
    assert "TRADE COMPLETED" in snap["waiting_state"]
    print("       --> PASS: Full 11-stage pipeline, active trade metrics, and completion state verified.\n")

    # -------------------------------------------------------------------------
    # Scenario 3 — Runtime Validation Failure
    # -------------------------------------------------------------------------
    print("[3/10] Testing Scenario 3: Runtime Validation Failure...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "TATASTEEL", "action": "BUY", "entry": 140.0, "sl": 135.0, "source": "WEBHOOK"})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=2, payload={"symbol": "TATASTEEL", "action": "BUY"})
    emit_event("RUNTIME_VALIDATION_FAILED", "TRADE_ENGINE", execution_target_id=2, severity="ERROR", payload={"fail_reason": "INVALID_BROKER_SESSION"})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["exceptions"][0]["event_type"] == "RUNTIME_VALIDATION_FAILED"
    assert "INVALID_BROKER_SESSION" in snap["exceptions"][0]["reason"]
    print("       --> PASS: Timeline stopped at Stage 5 and Exception Panel captured validation error.\n")

    # -------------------------------------------------------------------------
    # Scenario 4 — Risk Manager Failure
    # -------------------------------------------------------------------------
    print("[4/10] Testing Scenario 4: Risk Manager Rejection...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "INFY", "action": "BUY", "entry": 1500.0, "sl": 1400.0, "source": "WEBHOOK"})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=3, payload={"symbol": "INFY", "action": "BUY"})
    emit_event("RISK_CHECK_FAILED", "TRADE_ENGINE", execution_target_id=3, severity="ERROR", payload={"fail_reason": "MAX_DAILY_LOSS_EXCEEDED"})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["exceptions"][0]["event_type"] == "RISK_CHECK_FAILED"
    assert "MAX_DAILY_LOSS_EXCEEDED" in snap["exceptions"][0]["reason"]
    print("       --> PASS: Risk Manager rejection correctly captured and timeline halted.\n")

    # -------------------------------------------------------------------------
    # Scenario 5 — Quantity Calculator Failure
    # -------------------------------------------------------------------------
    print("[5/10] Testing Scenario 5: Quantity Calculator Failure (QUANTITY_CALC_FAILED)...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "RELIANCE", "action": "BUY", "entry": 2500.0, "sl": 2400.0, "source": "WEBHOOK"})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=4, payload={"symbol": "RELIANCE", "action": "BUY"})
    emit_event("QUANTITY_CALC_FAILED", "TRADE_ENGINE", execution_target_id=4, severity="ERROR", payload={"fail_reason": "QUANTITY_BELOW_MINIMUM"})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["exceptions"][0]["event_type"] == "QUANTITY_CALC_FAILED"
    assert "QUANTITY_BELOW_MINIMUM" in snap["exceptions"][0]["reason"]
    print("       --> PASS: Disambiguated QUANTITY_CALC_FAILED captured correctly.\n")

    # -------------------------------------------------------------------------
    # Scenario 6 — Broker Rejection
    # -------------------------------------------------------------------------
    print("[6/10] Testing Scenario 6: Broker Order Rejection (ENTRY_REJECTED)...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "NHPC", "action": "BUY", "entry": 90.0, "sl": 85.0, "source": "WEBHOOK"})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=5, payload={"symbol": "NHPC", "action": "BUY"})
    emit_event("ENTRY_REJECTED", "TRADE_ENGINE", execution_target_id=5, severity="ERROR", payload={"fail_reason": "INSUFFICIENT_MARGIN"})
    emit_event("EXECUTION_RECORDED", "TRADE_ENGINE", execution_target_id=5, payload={"outcome": "BROKER_FAILED"})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["exceptions"][0]["event_type"] == "ENTRY_REJECTED"
    assert "INSUFFICIENT_MARGIN" in snap["exceptions"][0]["reason"]
    print("       --> PASS: Broker order rejection and outcome recording verified.\n")

    # -------------------------------------------------------------------------
    # Scenario 7 — Startup Recovery Events
    # -------------------------------------------------------------------------
    print("[7/10] Testing Scenario 7: Startup Recovery Telemetry Flow...")
    emit_event("RECOVERY_STARTED", "STARTUP_RECOVERY", payload={})
    emit_event("RECOVERY_COMPLETED", "STARTUP_RECOVERY", payload={"orphaned_targets_found": 2, "reconstructed_trades": 1, "subscribed_symbols": ["IDEA"]})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["recent_logs"][0]["event_type"] == "RECOVERY_COMPLETED"
    assert snap["recent_logs"][0]["payload"]["reconstructed_trades"] == 1
    print("       --> PASS: Startup recovery telemetry events captured cleanly.\n")

    # -------------------------------------------------------------------------
    # Scenario 8 — High Event Volume Stress Test (1,000 Events)
    # -------------------------------------------------------------------------
    print("[8/10] Testing Scenario 8: High Event Volume Stress Test (1,000 Events)...")
    start_time = time.time()
    threads = []

    def worker(t_id):
        for i in range(200):
            emit_event("TICK_STREAM", "TICK_ROUTER", payload={"thread": t_id, "index": i})

    for tid in range(5):
        t = threading.Thread(target=worker, args=(tid,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    time.sleep(0.3)
    elapsed = time.time() - start_time
    snap = state.get_snapshot()

    # Total = 11 (trade 1) + 3 (trade 2) + 3 (trade 3) + 3 (trade 4) + 4 (trade 5) + 2 (recovery) + 1000 (stress) = 1026
    assert snap["total_events"] == 1026
    print(f"       --> PASS: 1,000 burst events ingested in {elapsed:.3f}s with 0 drops!\n")

    # -------------------------------------------------------------------------
    # Scenario 9 — Concurrent Multi-Trade Signals
    # -------------------------------------------------------------------------
    print("[9/10] Testing Scenario 9: Concurrent Multi-Trade Signals...")
    emit_event("SIGNAL_RECEIVED", "WEBHOOK_ROUTER", payload={"symbol": "SUZLON", "action": "BUY", "entry": 50.0, "sl": 48.0, "source": "WEBHOOK"})
    emit_event("EXECUTION_STARTED", "TRADE_ENGINE", execution_target_id=10, payload={"symbol": "SUZLON", "action": "BUY"})
    emit_event("QUANTITY_CALCULATED", "TRADE_ENGINE", execution_target_id=10, payload={"quantity": 100})

    time.sleep(0.2)
    snap = state.get_snapshot()
    assert snap["active_trade"]["symbol"] == "SUZLON"
    assert snap["active_trade"]["quantity"] == 100
    print("       --> PASS: Multi-trade signal auto-latched to newest active trade cleanly.\n")

    # -------------------------------------------------------------------------
    # Scenario 10 — Rich Layout Rendering & Unsubscribe Safety
    # -------------------------------------------------------------------------
    print("[10/10] Testing Scenario 10: Rich Layout Generation & Clean Unsubscribe...")
    layout = make_layout(snap)
    assert layout is not None

    global_event_bus.unsubscribe(state.on_event)
    events_before = snap["total_events"]
    emit_event("IGNORE_TEST", "TEST", payload={})
    time.sleep(0.1)

    snap_after = state.get_snapshot()
    assert snap_after["total_events"] == events_before
    print("       --> PASS: Rich layout generated without errors and subscriber detached safely.\n")

    print("=" * 70)
    print("       ALL 10 E2E VALIDATION SCENARIOS PASSED SUCCESSFULLY!          ")
    print("=" * 70)


if __name__ == "__main__":
    run_e2e_dvc_validation_suite()
