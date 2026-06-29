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
                instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(watchlist_id, instrument_id)
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
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT i.id, i.symbol, i.exchange, i.name, i.token
            FROM instruments i
            JOIN watchlist_items wi ON i.id = wi.instrument_id
            WHERE wi.watchlist_id = :watchlist_id
            ORDER BY i.symbol ASC;
        """), {"watchlist_id": watchlist_id})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching items for watchlist {watchlist_id}: {e}")
        return []
    finally:
        session.close()


def add_instrument_to_watchlist(watchlist_id: int, instrument_id: int) -> bool:
    """
    Adds an instrument to the watchlist.
    """
    session = SessionLocal()
    try:
        session.execute(text("""
            INSERT INTO watchlist_items (watchlist_id, instrument_id)
            VALUES (:watchlist_id, :instrument_id);
        """), {"watchlist_id": watchlist_id, "instrument_id": instrument_id})
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error adding instrument {instrument_id} to watchlist {watchlist_id}: {e}")
        return False
    finally:
        session.close()


def remove_instrument_from_watchlist(watchlist_id: int, instrument_id: int) -> bool:
    """
    Removes an instrument from the watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            DELETE FROM watchlist_items
            WHERE watchlist_id = :watchlist_id AND instrument_id = :instrument_id;
        """), {"watchlist_id": watchlist_id, "instrument_id": instrument_id})
        session.commit()
        return result.rowcount > 0
    except Exception as e:
        session.rollback()
        logger.error(f"Error removing instrument {instrument_id} from watchlist {watchlist_id}: {e}")
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


def check_instrument_in_watchlist(watchlist_id: int, instrument_id: int) -> bool:
    """
    Checks if an instrument is already present inside a watchlist.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT EXISTS(
                SELECT 1
                FROM watchlist_items
                WHERE watchlist_id = :watchlist_id AND instrument_id = :instrument_id
            );
        """), {"watchlist_id": watchlist_id, "instrument_id": instrument_id})
        return result.scalar() or False
    except Exception as e:
        logger.error(f"Error checking duplicate for watchlist {watchlist_id}: {e}")
        return False
    finally:
        session.close()

