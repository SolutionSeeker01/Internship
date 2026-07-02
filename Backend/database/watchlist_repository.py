from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)

def init_db() -> None:
    """
    Initializes and verifies the watchlists table schema inside PostgreSQL.
    """
    session = SessionLocal()
    try:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS watchlists (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS watchlist_items (
                id SERIAL PRIMARY KEY,
                watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
                instrument_id INTEGER,
                symbol VARCHAR(50) NOT NULL,
                exchange VARCHAR(20) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(watchlist_id, symbol, exchange)
            );
        """))
        session.commit()
        logger.info("Database tables 'watchlists' and 'watchlist_items' initialized and verified.")
    except Exception as e:
        session.rollback()
        logger.exception(f"Failed to initialize database schemas: {e}")
        raise
    finally:
        session.close()

def get_all_watchlists() -> list:
    """
    Retrieves all watchlists ordered by name ASC.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT id, name, created_at
            FROM watchlists
            ORDER BY name ASC;
        """))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching watchlists: {e}")
        return []
    finally:
        session.close()

def get_watchlist_by_id(watchlist_id: int) -> dict:
    """
    Retrieves a single watchlist by ID.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("SELECT id, name, created_at FROM watchlists WHERE id = :id;"),
            {"id": watchlist_id}
        )
        row = result.fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error(f"Error fetching watchlist by id {watchlist_id}: {e}")
        return None
    finally:
        session.close()

def create_watchlist(name: str) -> dict:
    """
    Creates a new watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("INSERT INTO watchlists (name) VALUES (:name) RETURNING id, name, created_at;"),
            {"name": name.strip()}
        )
        row = result.fetchone()
        session.commit()
        return dict(row._mapping) if row else None
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create watchlist: {e}")
        return None
    finally:
        session.close()

def rename_watchlist(watchlist_id: int, name: str) -> dict:
    """
    Renames an existing watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("UPDATE watchlists SET name = :name WHERE id = :id RETURNING id, name, created_at;"),
            {"id": watchlist_id, "name": name.strip()}
        )
        row = result.fetchone()
        session.commit()
        return dict(row._mapping) if row else None
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to rename watchlist {watchlist_id}: {e}")
        return None
    finally:
        session.close()

def delete_watchlist(watchlist_id: int) -> bool:
    """
    Deletes a watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("DELETE FROM watchlists WHERE id = :id;"),
            {"id": watchlist_id}
        )
        session.commit()
        return result.rowcount > 0
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete watchlist {watchlist_id}: {e}")
        return False
    finally:
        session.close()


def get_watchlist_items(watchlist_id: int) -> list:
    """
    Retrieves all instruments belonging to the selected watchlist, sorted alphabetically by symbol ASC.
    Performs a LEFT JOIN to ensure missing/unavailable catalog items are not silently discarded.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT wi.id, wi.symbol, wi.exchange, i.name, i.token,
                   (CASE WHEN i.id IS NOT NULL THEN true ELSE false END) as available
            FROM watchlist_items wi
            LEFT JOIN instruments i ON UPPER(wi.symbol) = UPPER(i.symbol) AND UPPER(wi.exchange) = UPPER(i.exchange)
            WHERE wi.watchlist_id = :watchlist_id
            ORDER BY wi.symbol ASC;
        """), {"watchlist_id": watchlist_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching items for watchlist {watchlist_id}: {e}")
        return []
    finally:
        session.close()


def add_instrument_to_watchlist(watchlist_id: int, symbol_or_id: any, exchange: str = None, instrument_id: int = None) -> bool:
    """
    Adds an instrument to the watchlist. Supports both legacy signature (watchlist_id, instrument_id)
    and new decoupled signature (watchlist_id, symbol, exchange, instrument_id).
    """
    session = SessionLocal()
    try:
        if isinstance(symbol_or_id, int):
            inst_id = symbol_or_id
            from database.instrument_repository import get_instrument_by_id
            inst = get_instrument_by_id(inst_id)
            if not inst:
                logger.error(f"Cannot resolve legacy instrument_id {inst_id} for watchlist addition.")
                return False
            symbol = inst["symbol"]
            exch = inst["exchange"]
            instrument_id = inst_id
        else:
            symbol = symbol_or_id
            exch = exchange

        session.execute(text("""
            INSERT INTO watchlist_items (watchlist_id, symbol, exchange, instrument_id)
            VALUES (:watchlist_id, :symbol, :exchange, :instrument_id);
        """), {
            "watchlist_id": watchlist_id,
            "symbol": symbol.upper().strip(),
            "exchange": exch.upper().strip() if exch else "NSE",
            "instrument_id": instrument_id
        })
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding instrument to watchlist: {e}")
        return False
    finally:
        session.close()


def remove_instrument_from_watchlist(watchlist_id: int, symbol_or_id: any, exchange: str = None) -> bool:
    """
    Removes an instrument from the watchlist. Supports both legacy signature (watchlist_id, instrument_id)
    and new decoupled signature (watchlist_id, symbol, exchange).
    """
    session = SessionLocal()
    try:
        if isinstance(symbol_or_id, int):
            wi = get_watchlist_item_by_id_or_instrument(watchlist_id, symbol_or_id)
            if not wi:
                return False
            symbol = wi["symbol"]
            exch = wi["exchange"]
        else:
            symbol = symbol_or_id
            exch = exchange

        result = session.execute(text("""
            DELETE FROM watchlist_items
            WHERE watchlist_id = :watchlist_id 
              AND UPPER(symbol) = UPPER(:symbol) 
              AND UPPER(exchange) = UPPER(:exchange);
        """), {
            "watchlist_id": watchlist_id,
            "symbol": symbol.upper().strip(),
            "exchange": exch.upper().strip() if exch else "NSE"
        })
        session.commit()
        return result.rowcount > 0
    except Exception as e:
        session.rollback()
        logger.error(f"Error removing instrument from watchlist: {e}")
        return False
    finally:
        session.close()


def get_watchlist_items_count(watchlist_id: int) -> int:
    """
    Returns the count of instruments inside the selected watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT count(*)
            FROM watchlist_items
            WHERE watchlist_id = :watchlist_id;
        """), {"watchlist_id": watchlist_id})
        return result.scalar() or 0
    except Exception as e:
        logger.error(f"Error counting items for watchlist {watchlist_id}: {e}")
        return 0
    finally:
        session.close()


def check_instrument_in_watchlist(watchlist_id: int, symbol_or_id: any, exchange: str = None) -> bool:
    """
    Checks if an instrument is already present inside a watchlist. Supports both legacy signature (watchlist_id, instrument_id)
    and new decoupled signature (watchlist_id, symbol, exchange).
    """
    session = SessionLocal()
    try:
        if isinstance(symbol_or_id, int):
            wi = get_watchlist_item_by_id_or_instrument(watchlist_id, symbol_or_id)
            return wi is not None
        else:
            symbol = symbol_or_id
            exch = exchange

        result = session.execute(text("""
            SELECT EXISTS(
                SELECT 1
                FROM watchlist_items
                WHERE watchlist_id = :watchlist_id 
                  AND UPPER(symbol) = UPPER(:symbol) 
                  AND UPPER(exchange) = UPPER(:exchange)
            );
        """), {
            "watchlist_id": watchlist_id,
            "symbol": symbol.upper().strip(),
            "exchange": exch.upper().strip() if exch else "NSE"
        })
        return result.scalar() or False
    except Exception as e:
        logger.error(f"Error checking duplicate for watchlist {watchlist_id}: {e}")
        return False
    finally:
        session.close()


def get_watchlist_item_by_id_or_instrument(watchlist_id: int, identifier: int) -> dict:
    """
    Retrieves a single watchlist item by database primary key ID or instrument_id.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, watchlist_id, instrument_id, symbol, exchange
            FROM watchlist_items
            WHERE watchlist_id = :watchlist_id
              AND (id = :identifier OR instrument_id = :identifier)
            LIMIT 1;
        """), {"watchlist_id": watchlist_id, "identifier": identifier})
        row = res.fetchone()
        return dict(row._mapping) if row else None
    except Exception as e:
        logger.error(f"Error finding watchlist item: {e}")
        return None
    finally:
        session.close()

