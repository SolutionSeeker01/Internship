from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError
from exceptions import DatabaseException
from typing import Optional

logger = get_logger(__name__)


def init_db() -> None:
    """
    Initializes and verifies the updated signals table schema inside PostgreSQL.
    Drops existing signals table to guarantee the schema is clean and minimal.
    """
    session = SessionLocal()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS signals (
                id SERIAL PRIMARY KEY,
                signal_uuid UUID NOT NULL DEFAULT gen_random_uuid(),
                action VARCHAR(10) NOT NULL,
                symbol VARCHAR(30) NOT NULL,
                entry NUMERIC(15,4) NOT NULL,
                stoploss NUMERIC(15,4) NOT NULL,
                timeframe VARCHAR(10) NOT NULL,
                signal_timestamp BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # --- Idempotent migrations: add columns if they do not already exist ---
        for migration in [
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_status VARCHAR(20)",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_reason TEXT",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS t1 NUMERIC(15,4)",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS t2 NUMERIC(15,4)",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS t3 NUMERIC(15,4)",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS strategy_id BIGINT",
        ]:
            session.execute(text(migration))

        session.commit()
        logger.info("Database table 'signals' initialized and verified with updated schema columns (including t1/t2/t3).")
    except SQLAlchemyError as e:
        session.rollback()
        logger.exception(f"Failed to initialize/migrate 'signals' database schema: {e}")
        raise DatabaseException("Failed to initialize/migrate signals database schema.", original_exception=e)
    finally:
        session.close()


def save_signal(
    action: str,
    symbol: str,
    entry: float,
    sl: float,
    timeframe: str,
    timestamp: int,
    status: str = "PENDING",
    validation_status: str = "VALIDATED",
    validation_reason: str = None,
    t1: float = None,
    t2: float = None,
    t3: float = None,
    strategy_id: Optional[int] = None,
    **kwargs
) -> bool:
    """
    Persists a validated signal payload with its lifecycle states into PostgreSQL signals table.
    Maps input stoploss (sl) parameter to database column `stoploss`.
    Persists pre-calculated targets t1, t2, t3 as immutable values for the audit trail.

    Returns:
        bool: True if insert transaction completed successfully.
    """
    session = SessionLocal()
    try:
        session.execute(
            text("""
                INSERT INTO signals (
                    action,
                    symbol,
                    entry,
                    stoploss,
                    timeframe,
                    signal_timestamp,
                    status,
                    validation_status,
                    validation_reason,
                    validated_at,
                    t1,
                    t2,
                    t3,
                    strategy_id
                )
                VALUES (
                    :action,
                    :symbol,
                    :entry,
                    :sl,
                    :timeframe,
                    :timestamp,
                    :status,
                    :validation_status,
                    :validation_reason,
                    CURRENT_TIMESTAMP,
                    :t1,
                    :t2,
                    :t3,
                    :strategy_id
                );
            """),
            {
                "action": action,
                "symbol": symbol,
                "entry": entry,
                "sl": sl,
                "timeframe": timeframe,
                "timestamp": timestamp,
                "status": status,
                "validation_status": validation_status,
                "validation_reason": validation_reason,
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "strategy_id": strategy_id,
            }
        )
        session.commit()
        logger.info(f"Signal persisted successfully: {action} {symbol} @ {entry} T1={t1} T2={t2} T3={t3} Status={status} ValStatus={validation_status}")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to persist signal {action} {symbol} to PostgreSQL: {e}")
        raise DatabaseException(f"Failed to persist signal {action} {symbol} to database.", original_exception=e)
    finally:
        session.close()


def check_duplicate_signal(symbol: str, action: str, entry: float) -> bool:
    """
    Checks if a signal with the same symbol, action, and entry price
    was received within the last 2 minutes.
    """
    session = SessionLocal()
    try:
        sql = """
            SELECT COUNT(*) 
            FROM signals
            WHERE UPPER(symbol) = :symbol
              AND UPPER(action) = :action
              AND entry = :entry
              AND created_at >= CURRENT_TIMESTAMP - INTERVAL '2 minutes';
        """
        count = session.execute(text(sql), {
            "symbol": symbol.upper().strip(),
            "action": action.upper().strip(),
            "entry": entry
        }).scalar()
        return count > 0
    except SQLAlchemyError as e:
        logger.error(f"Error checking duplicate signal: {e}")
        raise DatabaseException("Error checking duplicate signal from database.", original_exception=e)
    finally:
        session.close()


def get_accepted_signals(limit: int = 50, offset: int = 0) -> list:
    """
    Retrieves a paginated list of accepted signals (validation_status = 'VALIDATED' or 'PARTIAL').
    """
    session = SessionLocal()
    try:
        sql = """
            SELECT id, signal_uuid, action, symbol, entry, stoploss, timeframe, signal_timestamp, status, created_at, validation_status, validation_reason, validated_at, t1, t2, t3, strategy_id
            FROM signals
            WHERE validation_status IN ('VALIDATED', 'PARTIAL')
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset;
        """
        result = session.execute(text(sql), {"limit": limit, "offset": offset})
        return [dict(row._mapping) for row in result.all()]
    except SQLAlchemyError as e:
        logger.error(f"Error fetching accepted signals: {e}")
        raise DatabaseException("Error fetching accepted signals from database.", original_exception=e)
    finally:
        session.close()


def get_rejected_signals(limit: int = 50, offset: int = 0) -> list:
    """
    Retrieves a paginated list of rejected signals (validation_status = 'REJECTED').
    """
    session = SessionLocal()
    try:
        sql = """
            SELECT id, signal_uuid, action, symbol, entry, stoploss, timeframe, signal_timestamp, status, created_at, validation_status, validation_reason, validated_at, strategy_id
            FROM signals
            WHERE validation_status = 'REJECTED'
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset;
        """
        result = session.execute(text(sql), {"limit": limit, "offset": offset})
        return [dict(row._mapping) for row in result.all()]
    except SQLAlchemyError as e:
        logger.error(f"Error fetching rejected signals: {e}")
        raise DatabaseException("Error fetching rejected signals from database.", original_exception=e)
    finally:
        session.close()
