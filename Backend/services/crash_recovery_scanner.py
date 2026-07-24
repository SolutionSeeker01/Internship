# crash_recovery_scanner.py - Crash Recovery Scanner Service
'use strict'

import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from database.db import SessionLocal
from database.execution_writer_repository import record_execution_result
from models.execution_result import ExecutionResult
from services.brokers.factory import BrokerFactory
from utils.logger import get_logger

logger = get_logger(__name__)


def find_orphaned_executing_targets(timeout_seconds: int = 30, session: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Executes Section 5.14 Query:
      SELECT * FROM signal_execution_targets
      WHERE status = 'EXECUTING'
      AND claimed_at < NOW() - INTERVAL '30 seconds'
    """
    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        sql = text("""
            SELECT id, signal_id, client_id, status, idempotency_key, claimed_at
            FROM signal_execution_targets
            WHERE status = 'EXECUTING'
              AND claimed_at < (NOW() - (:seconds || ' seconds')::INTERVAL);
        """)
        rows = db.execute(sql, {"seconds": str(timeout_seconds)}).fetchall()
        
        targets = []
        for r in rows:
            targets.append({
                "id": int(r[0]),
                "signal_id": int(r[1]),
                "client_id": int(r[2]),
                "status": str(r[3]),
                "broker_order_id": None, # broker_order_id lives on orders table in V1 schema
                "idempotency_key": str(r[4]) if r[4] else "",
                "claimed_at": r[5]
            })
        return targets

    finally:
        if own_session:
            db.close()


def reconcile_target(target: Dict[str, Any], broker_adapter_override: Optional[Any] = None) -> str:
    """
    Reconciles a single orphaned EXECUTING target following Section 5.14 Decision Tree:
    
    1. broker_order_id IS NOT NULL:
       - query broker by ID
       - found: update DB to SUBMITTED
       - not found: ALERT (mark FAILED)
       
    2. broker_order_id IS NULL:
       - query broker using idempotency_key
       - order found: update DB to SUBMITTED
       - order not found: reset to READY (safe to retry)
       
    3. broker unreachable / exception:
       - leave as EXECUTING, retry in next cycle
    """
    target_id = target["id"]
    signal_id = target["signal_id"]
    client_id = target["client_id"]
    broker_order_id = target["broker_order_id"]
    idempotency_key = target["idempotency_key"]

    logger.info(f"Crash Recovery Scanner auditing target ID {target_id} (claimed_at={target['claimed_at']})...")

    # Resolve Broker Adapter via BrokerFactory or override
    broker_adapter = broker_adapter_override
    if not broker_adapter:
        # Resolve broker name for client from DB
        db = SessionLocal()
        try:
            from models.broker_account import BrokerAccount
            acc = db.query(BrokerAccount).filter(BrokerAccount.user_id == client_id).first()
            broker_name = acc.broker if acc and acc.broker else "ZERODHA"
            broker_adapter = BrokerFactory.get_broker(broker_name)
        except Exception as e:
            logger.error(f"Crash Recovery Scanner failed to resolve broker for client {client_id}: {e}")
            # Decision Tree Branch 3: broker unreachable -> leave as EXECUTING
            return "UNREACHABLE_RETRY_NEXT_CYCLE"
        finally:
            db.close()

    try:
        # Branch 1: broker_order_id IS NOT NULL
        if broker_order_id:
            logger.info(f"Crash Recovery querying broker for order_id '{broker_order_id}' target ID {target_id}...")
            order_info = broker_adapter.get_order_by_id(broker_order_id)
            
            if order_info:
                logger.info(f"[CRASH_RECOVERY_RECONCILED] Found order '{broker_order_id}' for target ID {target_id}. Updating status to SUBMITTED.")
                res = ExecutionResult(
                    execution_target_id=target_id,
                    signal_id=signal_id,
                    client_id=client_id,
                    outcome="SUBMITTED",
                    broker_order_id=broker_order_id,
                    idempotency_key=idempotency_key,
                    executed_at=datetime.now()
                )
                record_execution_result(res)
                return "RECONCILED_SUBMITTED"
            else:
                logger.critical(f"[CRASH_RECOVERY_ALERT] Order '{broker_order_id}' NOT FOUND at broker for target ID {target_id}! Marking FAILED.")
                res = ExecutionResult(
                    execution_target_id=target_id,
                    signal_id=signal_id,
                    client_id=client_id,
                    outcome="BROKER_FAILED",
                    fail_reason="CRASH_RECOVERY_ORDER_NOT_FOUND",
                    fail_category="PERMANENT",
                    idempotency_key=idempotency_key,
                    executed_at=datetime.now()
                )
                record_execution_result(res)
                return "MARKED_FAILED"

        # Branch 2: broker_order_id IS NULL
        else:
            logger.info(f"Crash Recovery querying broker using idempotency_key '{idempotency_key}' target ID {target_id}...")
            order_info = broker_adapter.get_order_by_tag(idempotency_key)
            
            if order_info and order_info.get("broker_order_id"):
                found_id = str(order_info["broker_order_id"])
                logger.info(f"[CRASH_RECOVERY_RECONCILED] Found order '{found_id}' via tag for target ID {target_id}. Updating status to SUBMITTED.")
                res = ExecutionResult(
                    execution_target_id=target_id,
                    signal_id=signal_id,
                    client_id=client_id,
                    outcome="SUBMITTED",
                    broker_order_id=found_id,
                    idempotency_key=idempotency_key,
                    executed_at=datetime.now()
                )
                record_execution_result(res)
                return "RECONCILED_SUBMITTED"
            else:
                # Safe to reset to READY for retry (Section 5.14)
                logger.info(f"[CRASH_RECOVERY_RESET] No order found for target ID {target_id}. Resetting status to READY for safe retry.")
                db = SessionLocal()
                try:
                    sql_reset = text("""
                        UPDATE signal_execution_targets
                        SET status = 'READY',
                            claimed_at = NULL,
                            updated_at = NOW()
                        WHERE id = :target_id AND status = 'EXECUTING';
                    """)
                    db.execute(sql_reset, {"target_id": target_id})
                    db.commit()
                    return "RESET_TO_READY"
                finally:
                    db.close()

    except Exception as err:
        # Branch 3: broker unreachable / network error during recovery -> leave as EXECUTING
        logger.warning(f"Crash Recovery Scanner broker unreachable for target ID {target_id}: {err}. Leaving as EXECUTING to retry next cycle.")
        return "UNREACHABLE_RETRY_NEXT_CYCLE"


def run_crash_recovery_scan(timeout_seconds: int = 30, broker_adapter_override: Optional[Any] = None) -> Dict[str, int]:
    """
    Executes a single complete crash recovery scan cycle.
    Used for server startup and periodic background scanning.
    """
    logger.info("Crash Recovery Scanner cycle starting...")
    targets = find_orphaned_executing_targets(timeout_seconds=timeout_seconds)
    
    summary = {
        "scanned": len(targets),
        "reconciled_submitted": 0,
        "marked_failed": 0,
        "reset_to_ready": 0,
        "unreachable": 0
    }

    if not targets:
        logger.info("Crash Recovery Scanner found 0 orphaned EXECUTING targets.")
        return summary

    logger.warning(f"Crash Recovery Scanner detected {len(targets)} orphaned EXECUTING target(s) > {timeout_seconds}s old.")
    
    for t in targets:
        outcome = reconcile_target(t, broker_adapter_override=broker_adapter_override)
        if outcome == "RECONCILED_SUBMITTED":
            summary["reconciled_submitted"] += 1
        elif outcome == "MARKED_FAILED":
            summary["marked_failed"] += 1
        elif outcome == "RESET_TO_READY":
            summary["reset_to_ready"] += 1
        elif outcome == "UNREACHABLE_RETRY_NEXT_CYCLE":
            summary["unreachable"] += 1

    logger.info(f"Crash Recovery Scanner cycle complete: {summary}")
    return summary


# Background Daemon Thread Runner for Periodic Execution (Section 5.14)
_scanner_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _periodic_scan_loop(interval_seconds: int = 60):
    logger.info(f"Crash Recovery Scanner periodic background loop started (interval={interval_seconds}s).")
    while not _stop_event.is_set():
        try:
            run_crash_recovery_scan(timeout_seconds=30)
        except Exception as e:
            logger.error(f"Error in Crash Recovery Scanner background loop: {e}")
        
        # Sleep interval with interruptible check
        _stop_event.wait(timeout=interval_seconds)


def start_crash_recovery_scanner(interval_seconds: int = 60):
    """
    Starts the periodic Crash Recovery Scanner background task (runs at startup + every interval_seconds).
    """
    global _scanner_thread
    # 1. Immediate startup scan
    try:
        run_crash_recovery_scan(timeout_seconds=30)
    except Exception as e:
        logger.error(f"Startup Crash Recovery scan failed: {e}")

    # 2. Spawn periodic background thread
    _stop_event.clear()
    _scanner_thread = threading.Thread(target=_periodic_scan_loop, args=(interval_seconds,), daemon=True)
    _scanner_thread.start()
    logger.info("Crash Recovery Scanner background thread launched successfully.")


def stop_crash_recovery_scanner():
    """
    Stops the periodic background scanner thread gracefully.
    """
    global _scanner_thread
    _stop_event.set()
    if _scanner_thread and _scanner_thread.is_alive():
        _scanner_thread.join(timeout=5)
        logger.info("Crash Recovery Scanner background thread stopped.")
