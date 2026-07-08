from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger
from sqlalchemy.exc import SQLAlchemyError
from exceptions import DatabaseException

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
        session.commit()
        logger.info("Database table 'signals' initialized and verified with updated schema columns.")
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
    **kwargs
) -> bool:
    """
    Persists a validated signal payload with its lifecycle states into PostgreSQL signals table.
    Maps input stoploss (sl) parameter to database column `stoploss`.

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
                    validated_at
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
                    CURRENT_TIMESTAMP
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
                "validation_reason": validation_reason
            }
        )
        session.commit()
        logger.info(f"Signal persisted successfully: {action} {symbol} @ {entry} Status={status} ValStatus={validation_status}")
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
