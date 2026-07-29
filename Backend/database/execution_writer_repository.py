# execution_writer_repository.py - Execution Writer Persistence Operations
'use strict'

from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from database.db import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)


def record_execution_result(
    execution_result: Any,
    order_spec: Optional[Any] = None,
    session: Optional[Session] = None
) -> bool:
    """
    Persists an ExecutionResult to PostgreSQL:
      1. Conditionally updates signal_execution_targets status from 'EXECUTING' to final outcome status.
      2. If outcome == 'SUBMITTED', inserts a new record into the orders table.
      
    Implements Section 5.13 (Execution Writer) and Section 11 of Architecture Reference v1.3.
    """
    target_id = getattr(execution_result, "execution_target_id", 0)
    outcome = getattr(execution_result, "outcome", "INTERNAL_ERROR")
    broker_order_id = getattr(execution_result, "broker_order_id", None)
    fail_reason = getattr(execution_result, "fail_reason", None)
    fail_category = getattr(execution_result, "fail_category", None)
    idempotency_key = getattr(execution_result, "idempotency_key", "")
    executed_at = getattr(execution_result, "executed_at", None) or datetime.now()

    # Map pipeline outcome to DB target status per State Machine (Section 6)
    target_status = outcome # SUBMITTED, RUNTIME_REJECTED, RISK_REJECTED, or BROKER_FAILED (mapped to FAILED)
    if outcome == "BROKER_FAILED":
        target_status = "FAILED"

    own_session = False
    db = session
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        # Step 1: Enforce State Machine via Conditional UPDATE (Section 6 & Section 8)
        sql_target_update = text("""
            UPDATE signal_execution_targets
            SET status = :status,
                fail_reason = :fail_reason,
                fail_category = :fail_category,
                idempotency_key = COALESCE(NULLIF(:idempotency_key, ''), idempotency_key),
                executed_at = :executed_at,
                updated_at = NOW()
            WHERE id = :target_id AND status = 'EXECUTING'
            RETURNING id;
        """)

        res_update = db.execute(sql_target_update, {
            "status": target_status,
            "fail_reason": fail_reason,
            "fail_category": fail_category,
            "idempotency_key": idempotency_key,
            "executed_at": executed_at,
            "target_id": target_id
        })


        row = res_update.fetchone()
        if not row:
            logger.warning(f"Execution Writer conditional UPDATE updated 0 rows for target ID {target_id}. Target may not be in 'EXECUTING' state.")

        # Step 2: If outcome == 'SUBMITTED', create orders table record
        if outcome == "SUBMITTED":
            symbol = getattr(order_spec, "symbol", "") if order_spec else ""
            exchange = getattr(order_spec, "exchange", "NSE") if order_spec else "NSE"
            action = getattr(order_spec, "action", "BUY") if order_spec else "BUY"
            order_type = getattr(order_spec, "order_type", "MARKET") if order_spec else "MARKET"
            quantity = getattr(order_spec, "quantity", 1) if order_spec else int(getattr(execution_result, "quantity", 1) or 1)
            price = getattr(order_spec, "price", None) if order_spec else getattr(execution_result, "executed_price", None)
            trigger_price = getattr(order_spec, "trigger_price", None) if order_spec else None
            broker = getattr(order_spec, "broker", "ZERODHA") if order_spec else "ZERODHA"

            sql_order_insert = text("""
                INSERT INTO orders (
                    execution_target_id,
                    parent_order_id,
                    order_role,
                    broker_order_id,
                    idempotency_key,
                    symbol,
                    exchange,
                    action,
                    order_type,
                    quantity,
                    price,
                    trigger_price,
                    status,
                    filled_quantity,
                    average_price,
                    broker,
                    placed_at,
                    created_at
                ) VALUES (
                    :execution_target_id,
                    NULL,
                    'ENTRY',
                    :broker_order_id,
                    :idempotency_key,
                    :symbol,
                    :exchange,
                    :action,
                    :order_type,
                    :quantity,
                    :price,
                    :trigger_price,
                    'PLACED',
                    0,
                    NULL,
                    :broker,
                    :placed_at,
                    NOW()
                ) RETURNING id;
            """)

            res_order = db.execute(sql_order_insert, {
                "execution_target_id": target_id,
                "broker_order_id": broker_order_id,
                "idempotency_key": idempotency_key,
                "symbol": symbol,
                "exchange": exchange,
                "action": action,
                "order_type": order_type,
                "quantity": quantity,
                "price": price,
                "trigger_price": trigger_price,
                "broker": broker,
                "placed_at": executed_at
            })
            inserted_order_row = res_order.fetchone()
            if inserted_order_row:
                logger.info(f"Execution Writer persisted entry order ID {inserted_order_row[0]} for target ID {target_id}.")

            # Step 3: Create Trade record and register with RuntimeCoordinator for live tick monitoring & trailing SL
            try:
                from decimal import Decimal
                from database import trade_repository
                trade = trade_repository.get_trade_by_execution_target_id(target_id, session=db)
                if not trade:
                    sql_sig = text("""
                        SELECT s.entry, s.stoploss, s.t1, s.t2, s.t3
                        FROM signals s
                        JOIN signal_execution_targets set_target ON set_target.signal_id = s.id
                        WHERE set_target.id = :target_id;
                    """)
                    sig_row = db.execute(sql_sig, {"target_id": target_id}).fetchone()
                    if sig_row:
                        trade = trade_repository.create_trade(
                            execution_target_id=target_id,
                            entry_intended_price=Decimal(str(sig_row[0])),
                            sl_intended=Decimal(str(sig_row[1])),
                            t1_intended=Decimal(str(sig_row[2])) if sig_row[2] is not None else None,
                            t2_intended=Decimal(str(sig_row[3])) if sig_row[3] is not None else None,
                            t3_intended=Decimal(str(sig_row[4])) if sig_row[4] is not None else None,
                            status="OPEN",
                            session=db
                        )

                sql_client = text("""
                    SELECT set_target.client_id, ba.id AS broker_account_id
                    FROM signal_execution_targets set_target
                    LEFT JOIN broker_accounts ba ON ba.user_id = set_target.client_id
                    WHERE set_target.id = :target_id;
                """)
                client_row = db.execute(sql_client, {"target_id": target_id}).fetchone()
                broker_account_id = client_row[1] if client_row and client_row[1] else None

                if trade and broker_account_id:
                    from services.runtime.runtime_coordinator import get_runtime_coordinator
                    coordinator = get_runtime_coordinator()
                    if coordinator and coordinator._is_initialized:
                        coordinator.register_and_start_trade(
                            trade_id=trade.id,
                            symbol=symbol,
                            broker_account_id=broker_account_id
                        )
            except Exception as trade_reg_err:
                logger.error(f"Execution Writer encountered error creating/registering trade for target ID {target_id}: {trade_reg_err}", exc_info=True)

        if own_session:
            db.commit()
        return True

    except Exception as e:
        if own_session:
            db.rollback()
        logger.error(f"Execution Writer persistence error for target ID {target_id}: {e}")
        raise
    finally:
        if own_session:
            db.close()
