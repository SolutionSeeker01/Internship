from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)

def init_db() -> None:
    """
    Initializes and verifies the instruments table schema inside PostgreSQL.
    Also executes migrations to add the category column if it is missing.
    """
    session = SessionLocal()
    try:
        # 1. Create table if not exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS instruments (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(50) UNIQUE NOT NULL,
                token INTEGER NOT NULL,
                exchange VARCHAR(20),
                name VARCHAR(100),
                segment VARCHAR(50),
                broker VARCHAR(50),
                active BOOLEAN NOT NULL DEFAULT TRUE,
                is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
                instrument_category VARCHAR(20) NOT NULL DEFAULT 'STOCK',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))
        session.commit()

        # 2. Add column if table existed but column was missing
        session.execute(text("""
            ALTER TABLE instruments ADD COLUMN IF NOT EXISTS instrument_category VARCHAR(20) NOT NULL DEFAULT 'STOCK';
        """))
        session.commit()

        # 3. Migrate indices
        session.execute(text("""
            UPDATE instruments 
            SET instrument_category = 'INDEX' 
            WHERE symbol IN ('NIFTY50', 'BANKNIFTY', 'SENSEX') AND (instrument_category IS NULL OR instrument_category = 'STOCK');
        """))
        session.commit()

        logger.info("Database table 'instruments' initialized, verified, and migrated.")
    except Exception as e:
        session.rollback()
        logger.exception(f"Failed to initialize 'instruments' database schema or run migrations: {e}")
        raise
    finally:
        session.close()

def get_all_instruments() -> list:
    """
    Retrieves all instruments stored in the database.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
            FROM instruments
            ORDER BY symbol ASC;
        """))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching all instruments: {e}")
        return []
    finally:
        session.close()

def create_instrument(symbol: str, token: int, exchange: str, name: str, segment: str, broker: str, instrument_category: str = "STOCK") -> bool:
    """
    Creates a new instrument.
    """
    session = SessionLocal()
    try:
        session.execute(
            text("""
                INSERT INTO instruments (symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category)
                VALUES (:symbol, :token, :exchange, :name, :segment, :broker, TRUE, FALSE, :instrument_category)
                ON CONFLICT (symbol) DO UPDATE SET
                    token = EXCLUDED.token,
                    exchange = EXCLUDED.exchange,
                    name = EXCLUDED.name,
                    segment = EXCLUDED.segment,
                    broker = EXCLUDED.broker,
                    instrument_category = EXCLUDED.instrument_category,
                    updated_at = CURRENT_TIMESTAMP;
            """),
            {
                "symbol": symbol.upper().strip(),
                "token": token,
                "exchange": exchange.strip(),
                "name": name.strip(),
                "segment": segment.strip(),
                "broker": broker.strip(),
                "instrument_category": instrument_category.strip()
            }
        )
        session.commit()
        logger.info(f"Instrument '{symbol}' created or updated successfully with category '{instrument_category}'.")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create instrument {symbol}: {e}")
        return False
    finally:
        session.close()

def delete_instrument(symbol: str) -> bool:
    """
    Deletes an instrument by its symbol.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("DELETE FROM instruments WHERE UPPER(symbol) = :symbol;"),
            {"symbol": symbol.upper().strip()}
        )
        session.commit()
        if result.rowcount > 0:
            logger.info(f"Instrument '{symbol}' deleted successfully.")
            return True
        else:
            logger.warning(f"Instrument '{symbol}' not found for deletion.")
            return False
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete instrument {symbol}: {e}")
        return False
    finally:
        session.close()


def toggle_favorite(symbol: str, is_favorite: bool) -> bool:
    """
    Updates the favorite status of an instrument.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("""
                UPDATE instruments
                SET is_favorite = :is_favorite, updated_at = CURRENT_TIMESTAMP
                WHERE UPPER(symbol) = :symbol;
            """),
            {"symbol": symbol.upper().strip(), "is_favorite": is_favorite}
        )
        session.commit()
        if result.rowcount > 0:
            logger.info(f"Instrument '{symbol}' favorite state set to {is_favorite}.")
            return True
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to update favorite state for {symbol}: {e}")
        return False
    finally:
        session.close()

def get_favorite_instruments() -> list:
    """
    Retrieves all instruments that are active and marked as favorite.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
            FROM instruments
            WHERE active = TRUE AND is_favorite = TRUE
            ORDER BY symbol ASC;
        """))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching favorite instruments: {e}")
        return []
    finally:
        session.close()


def check_duplicate(symbol: str, token: int) -> dict:
    """
    Checks if an instrument with the given symbol or token already exists in database.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT 
                EXISTS(SELECT 1 FROM instruments WHERE UPPER(symbol) = UPPER(:symbol)) as symbol_exists,
                EXISTS(SELECT 1 FROM instruments WHERE token = :token) as token_exists;
        """), {"symbol": symbol.upper().strip(), "token": token})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return {"symbol_exists": False, "token_exists": False}
    except Exception as e:
        logger.error(f"Error checking duplicate instrument: {e}")
        return {"symbol_exists": False, "token_exists": False}
    finally:
        session.close()
