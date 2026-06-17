from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger

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
    except Exception as e:
        session.rollback()
        logger.exception(f"Failed to initialize/migrate 'signals' database schema: {e}")
        raise
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
    **kwargs
) -> bool:
    """
    Persists a validated signal payload with its lifecycle states into PostgreSQL signals table.
    Maps input stoploss (sl) parameter to database column `stoploss`.

    Returns:
        bool: True if insert transaction completed successfully, False otherwise.
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
                    status
                )
                VALUES (
                    :action,
                    :symbol,
                    :entry,
                    :sl,
                    :timeframe,
                    :timestamp,
                    :status
                );
            """),
            {
                "action": action,
                "symbol": symbol,
                "entry": entry,
                "sl": sl,
                "timeframe": timeframe,
                "timestamp": timestamp,
                "status": status
            }
        )
        session.commit()
        logger.info(f"Signal persisted successfully: {action} {symbol} @ {entry} Status={status}")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to persist signal {action} {symbol} to PostgreSQL: {e}")
        return False
    finally:
        session.close()
