from typing import Optional
from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger
from database.defaults import DEFAULT_SYMBOLS, DEFAULT_STOCKS, DEFAULT_INDICES
from sqlalchemy.exc import SQLAlchemyError
from exceptions import DatabaseException

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
            SET instrument_category = 'INDEX', segment = 'IND'
            WHERE UPPER(symbol) IN ('NIFTY50', 'BANKNIFTY', 'SENSEX', 'NIFTY 50', 'NIFTY BANK') 
              AND (instrument_category != 'INDEX' OR segment != 'IND');
        """))
        session.commit()

        logger.info("Database table 'instruments' initialized, verified, and migrated.")
    except SQLAlchemyError as e:
        session.rollback()
        logger.exception(f"Failed to initialize 'instruments' database schema or run migrations: {e}")
        raise DatabaseException("Failed to initialize instruments database schema.", original_exception=e)
    finally:
        session.close()

def get_all_instruments() -> list:
    """
    Retrieves all instruments stored in the database.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category, created_at, updated_at
            FROM instruments
            ORDER BY symbol ASC;
        """))
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except SQLAlchemyError as e:
        logger.error(f"Error fetching all instruments: {e}")
        raise DatabaseException("Error fetching all instruments from database.", original_exception=e)
    finally:
        session.close()

def search_instruments(query: str, limit: int = 20) -> list:
    """
    Search instruments by symbol, name, exchange, segment, broker, category, or token with a limit.
    Results are ranked by match relevance:
    1. Exact symbol match
    2. Symbol starts with query
    3. Symbol contains query
    4. Company name contains query
    5. Exchange, Segment, Category, Broker, or Token match
    """
    session = SessionLocal()
    try:
        clean_query = query.upper().strip()
        is_numeric = clean_query.isdigit()
        
        sql = """
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category, created_at, updated_at
            FROM instruments
            WHERE UPPER(symbol) LIKE :contains_query
               OR UPPER(name) LIKE :contains_query
               OR UPPER(exchange) LIKE :contains_query
               OR UPPER(segment) LIKE :contains_query
               OR UPPER(broker) LIKE :contains_query
               OR UPPER(instrument_category) LIKE :contains_query
               OR CAST(token AS VARCHAR) LIKE :contains_query
        """
        
        params = {
            "exact_query": clean_query,
            "starts_with_query": f"{clean_query}%",
            "contains_query": f"%{clean_query}%",
            "limit": limit
        }
        
        if is_numeric:
            sql += " OR token = :token_val"
            params["token_val"] = int(clean_query)
            
        sql += """
            ORDER BY 
                CASE
                    WHEN UPPER(symbol) = :exact_query THEN 1
                    WHEN UPPER(symbol) LIKE :starts_with_query THEN 2
                    WHEN UPPER(symbol) LIKE :contains_query THEN 3
                    WHEN UPPER(name) LIKE :contains_query THEN 4
                    ELSE 5
                END ASC,
                symbol ASC
            LIMIT :limit;
        """
        
        result = session.execute(text(sql), params)
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    except SQLAlchemyError as e:
        logger.error(f"Error searching instruments with query '{query}': {e}")
        raise DatabaseException("Error searching instruments in database.", original_exception=e)
    finally:
        session.close()

def get_instrument_by_symbol(symbol: str) -> dict:
    """
    Retrieves a single instrument by symbol only.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category
            FROM instruments
            WHERE UPPER(symbol) = :symbol;
        """), {"symbol": symbol.upper().strip()})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except SQLAlchemyError as e:
        logger.error(f"Error fetching instrument by symbol {symbol}: {e}")
        raise DatabaseException(f"Error fetching instrument by symbol {symbol} from database.", original_exception=e)
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
                INSERT INTO instruments (symbol, token, exchange, name, segment, broker, instrument_category)
                VALUES (:symbol, :token, :exchange, :name, :segment, :broker, :instrument_category)
                ON CONFLICT (symbol, exchange) DO UPDATE SET
                    token = EXCLUDED.token,
                    name = EXCLUDED.name,
                    segment = EXCLUDED.segment,
                    broker = EXCLUDED.broker,
                    instrument_category = EXCLUDED.instrument_category,
                    updated_at = CURRENT_TIMESTAMP;
            """),
            {
                "symbol": symbol.upper().strip(),
                "token": token,
                "exchange": exchange.upper().strip(),
                "name": name.strip(),
                "segment": segment.strip(),
                "broker": broker.strip(),
                "instrument_category": instrument_category.strip()
            }
        )
        session.commit()
        logger.info(f"Instrument '{symbol}' ({exchange}) created or updated successfully with category '{instrument_category}'.")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to create instrument {symbol} ({exchange}): {e}")
        raise DatabaseException("Failed to create instrument in database.", original_exception=e)
    finally:
        session.close()

def delete_instrument(symbol: str, exchange: str) -> bool:
    """
    Deletes an instrument by its symbol and exchange.
    """
    session = SessionLocal()
    try:
        result = session.execute(
            text("DELETE FROM instruments WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;"),
            {"symbol": symbol.upper().strip(), "exchange": exchange.upper().strip()}
        )
        session.commit()
        if result.rowcount > 0:
            logger.info(f"Instrument '{symbol}' ({exchange}) deleted successfully.")
            return True
        else:
            logger.warning(f"Instrument '{symbol}' ({exchange}) not found for deletion.")
            return False
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to delete instrument {symbol} ({exchange}): {e}")
        raise DatabaseException("Failed to delete instrument from database.", original_exception=e)
    finally:
        session.close()


def delete_instruments_bulk(targets: list) -> int:
    """
    Deletes multiple instruments from database atomically in a single transaction.
    """
    session = SessionLocal()
    try:
        deleted_count = 0
        for target in targets:
            symbol = target["symbol"].upper().strip()
            exchange = target["exchange"].upper().strip()
            result = session.execute(
                text("DELETE FROM instruments WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;"),
                {"symbol": symbol, "exchange": exchange}
            )
            deleted_count += result.rowcount
        session.commit()
        logger.info(f"Bulk deleted {deleted_count} instruments successfully.")
        return deleted_count
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed bulk deletion transaction: {e}")
        raise DatabaseException("Failed bulk deletion transaction in database.", original_exception=e)
    finally:
        session.close()


def upsert_instruments_bulk(instruments_list: list) -> dict:
    """
    UPSERTS a list of instruments into the database.
    Updates only metadata.
    """
    session = SessionLocal()
    imported = 0
    updated = 0
    skipped = 0
    try:
        # Pre-query existing instruments' symbol+exchange pairs to determine imported vs updated
        # And load token to symbol+exchange map to handle token recycling conflicts
        existing_res = session.execute(text("SELECT symbol, exchange, token FROM instruments;"))
        existing_set = set()
        existing_tokens = {} # token -> (symbol, exchange)
        for row in existing_res.fetchall():
            sym = row._mapping["symbol"].upper()
            exch = row._mapping["exchange"].upper()
            tok = int(row._mapping["token"])
            existing_set.add((sym, exch))
            existing_tokens[tok] = (sym, exch)

        delete_params = []
        insert_params = []

        # Identify token recycling conflicts and delete stale rows before bulk inserts/updates
        recycled_tokens_to_delete = []
        for inst in instruments_list:
            symbol = inst["symbol"].upper().strip()
            exchange = inst["exchange"].upper().strip()
            token = int(inst["token"])

            if token in existing_tokens:
                ex_sym, ex_exch = existing_tokens[token]
                if ex_sym != symbol or ex_exch != exchange:
                    recycled_tokens_to_delete.append(token)
                    # Remove it from existing sets/maps so update counters stay accurate
                    existing_set.discard((ex_sym, ex_exch))

        if recycled_tokens_to_delete:
            # Delete in chunks to avoid query parameter size constraints
            chunk_size = 5000
            for i in range(0, len(recycled_tokens_to_delete), chunk_size):
                chunk = recycled_tokens_to_delete[i:i+chunk_size]
                session.execute(
                    text("DELETE FROM instruments WHERE token IN :tokens;"),
                    {"tokens": tuple(chunk)}
                )
            logger.info(f"Purged {len(recycled_tokens_to_delete)} stale instruments due to Zerodha token recycling.")

        for inst in instruments_list:
            symbol = inst["symbol"].upper().strip()
            exchange = inst["exchange"].upper().strip()
            token = inst["token"]
            name = inst["name"]
            segment = inst["segment"]
            broker = inst["broker"]
            category = inst["instrument_category"]

            delete_params.append({"symbol": symbol, "exchange": exchange})
            insert_params.append({
                "symbol": symbol,
                "token": token,
                "exchange": exchange,
                "name": name,
                "segment": segment,
                "broker": broker,
                "category": category
            })

            if (symbol, exchange) in existing_set:
                updated += 1
            else:
                imported += 1
                existing_set.add((symbol, exchange))

        # ON CONFLICT (symbol, exchange) DO UPDATE below handles upserts atomically and safely.
        # No pre-deletion of different exchange rows for the same symbol is required.

        if insert_params:
            session.execute(
                text("""
                    INSERT INTO instruments (symbol, token, exchange, name, segment, broker, instrument_category)
                    VALUES (:symbol, :token, :exchange, :name, :segment, :broker, :category)
                    ON CONFLICT (symbol, exchange) DO UPDATE SET
                        token = EXCLUDED.token,
                        name = EXCLUDED.name,
                        segment = EXCLUDED.segment,
                        broker = EXCLUDED.broker,
                        instrument_category = EXCLUDED.instrument_category,
                        updated_at = CURRENT_TIMESTAMP;
                """),
                insert_params
            )
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Bulk upsert failed: {e}")
        raise DatabaseException("Bulk upsert of instruments failed in database.", original_exception=e)
    finally:
        session.close()
    return {"imported": imported, "updated": updated, "skipped": skipped}

def check_duplicate(symbol: str, exchange: str, token: int) -> dict:
    """
    Checks if an instrument with the given symbol + exchange or token already exists in database.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT 
                EXISTS(SELECT 1 FROM instruments WHERE UPPER(symbol) = UPPER(:symbol) AND UPPER(exchange) = UPPER(:exchange)) as symbol_exists,
                EXISTS(SELECT 1 FROM instruments WHERE token = :token) as token_exists;
        """), {"symbol": symbol.upper().strip(), "exchange": exchange.upper().strip(), "token": token})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return {"symbol_exists": False, "token_exists": False}
    except SQLAlchemyError as e:
        logger.error(f"Error checking duplicate instrument: {e}")
        raise DatabaseException("Error checking duplicate instrument in database.", original_exception=e)
    finally:
        session.close()


def get_dashboard_watchlist(watchlist_id: int = None) -> dict:
    """
    Returns the instruments the dashboard should render, with indices fallback
    and stocks loaded either from selected watchlist or default fallback market view.

    Response structure:
        {
            "indices": [...],
            "stocks":  [...],
            "view_mode": "fallback" | "watchlist" | "empty",
            "selected_watchlist_id": int | None
        }
    """
    session = SessionLocal()
    try:
        columns = "id, symbol, token, exchange, name, segment, broker, instrument_category, created_at, updated_at"

        # ── Indices (strictly category = 'INDEX') ────────────────
        DASHBOARD_TOP_INDICES = [
            "NIFTY50",
            "NIFTY 50",
            "BANKNIFTY",
            "NIFTY BANK",
            "SENSEX"
        ]
        
        placeholders = ", ".join([f":idx_{i}" for i in range(len(DASHBOARD_TOP_INDICES))])
        params = {f"idx_{i}": sym for i, sym in enumerate(DASHBOARD_TOP_INDICES)}
        
        indices_result = session.execute(text(f"""
            SELECT {columns}
            FROM instruments
            WHERE UPPER(symbol) IN ({placeholders})
              AND UPPER(instrument_category) = 'INDEX'
            ORDER BY symbol ASC;
        """), params)
        indices = [dict(row._mapping) for row in indices_result.fetchall()]

        # ── Stocks & Others (strictly category != 'INDEX') ────────
        stocks = []
        view_mode = "fallback"
        resolved_watchlist_id = None

        if watchlist_id is not None:
            # 1. Verify watchlist exists
            res = session.execute(text("SELECT id FROM watchlists WHERE id = :id;"), {"id": watchlist_id})
            watchlist_record = res.fetchone()
            if not watchlist_record:
                # Watchlist does not exist. Fallback to empty mode as per instruction 5
                logger.warning(f"Watchlist with id={watchlist_id} requested but does not exist in DB.")
                view_mode = "empty"
                stocks = []
            else:
                resolved_watchlist_id = watchlist_id
                # 2. Query watchlist items LEFT JOIN instruments using symbol and exchange
                stocks_result = session.execute(text(f"""
                    SELECT i.id, wi.symbol, i.token, wi.exchange, i.name, i.segment, i.broker, i.instrument_category, i.created_at, i.updated_at
                    FROM watchlist_items wi
                    LEFT JOIN instruments i ON UPPER(wi.symbol) = UPPER(i.symbol) AND UPPER(wi.exchange) = UPPER(i.exchange)
                    WHERE wi.watchlist_id = :watchlist_id
                      AND i.id IS NOT NULL
                    ORDER BY wi.symbol ASC;
                """), {"watchlist_id": watchlist_id})
                stocks = [dict(row._mapping) for row in stocks_result.fetchall()]
                view_mode = "watchlist" if stocks else "empty"
        else:
            # Default market view: query by priority-ordered default stock symbols
            if DEFAULT_STOCKS:
                placeholders = ", ".join([f":stk_{i}" for i in range(len(DEFAULT_STOCKS))])
                params = {f"stk_{i}": sym for i, sym in enumerate(DEFAULT_STOCKS)}
                fallback_stocks_result = session.execute(text(f"""
                    SELECT {columns}
                    FROM instruments
                    WHERE UPPER(instrument_category) != 'INDEX'
                      AND UPPER(symbol) IN ({placeholders})
                """), params)
                fallback_map = {}
                for row in fallback_stocks_result.fetchall():
                    row_dict = dict(row._mapping)
                    fallback_map[row_dict["symbol"].upper()] = row_dict
                # Preserve priority ordering
                stocks = [fallback_map[s.upper()] for s in DEFAULT_STOCKS if s.upper() in fallback_map]
                view_mode = "fallback"
            else:
                stocks = []
                view_mode = "empty"

        return {
            "indices": indices,
            "stocks": stocks,
            "view_mode": view_mode,
            "selected_watchlist_id": resolved_watchlist_id
        }

    except SQLAlchemyError as e:
        logger.error(f"Error fetching dashboard watchlist: {e}")
        raise DatabaseException("Error fetching dashboard watchlist from database.", original_exception=e)

    finally:
        session.close()


def delete_all_instruments() -> int:
    """
    Deletes ALL instruments from the database.
    Returns the number of rows deleted.
    """
    session = SessionLocal()
    try:
        result = session.execute(text("DELETE FROM instruments;"))
        session.commit()
        count = result.rowcount
        logger.info(f"All instruments deleted. Rows affected: {count}")
        return count
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Failed to delete all instruments: {e}")
        raise DatabaseException("Failed to delete all instruments from database.", original_exception=e)
    finally:
        session.close()


def get_instrument_by_symbol_exchange(symbol: str, exchange: str) -> dict:
    """
    Retrieves a single instrument by symbol and exchange.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category
            FROM instruments
            WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;
        """), {"symbol": symbol.upper().strip(), "exchange": exchange.upper().strip()})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except SQLAlchemyError as e:
        logger.error(f"Error fetching instrument {symbol} on {exchange}: {e}")
        raise DatabaseException(f"Error fetching instrument {symbol} on {exchange} from database.", original_exception=e)
    finally:
        session.close()


def get_instrument_by_id(instrument_id: int) -> dict:
    """
    Retrieves a single instrument by database ID.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category
            FROM instruments
            WHERE id = :id;
        """), {"id": instrument_id})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except SQLAlchemyError as e:
        logger.error(f"Error fetching instrument by id {instrument_id}: {e}")
        raise DatabaseException(f"Error fetching instrument by id {instrument_id} from database.", original_exception=e)
    finally:
        session.close()


def find_instrument(symbol: str, broker: Optional[str] = None) -> Optional[dict]:
    """
    Finds a single instrument metadata record matching the symbol and optional broker scope.
    """
    session = SessionLocal()
    try:
        query = """
            SELECT id, symbol, token, exchange, name, segment, broker, instrument_category
            FROM instruments
            WHERE UPPER(symbol) = :symbol
        """
        params = {"symbol": symbol.upper().strip()}
        if broker:
            query += " AND UPPER(broker) = :broker"
            params["broker"] = broker.upper().strip()
        
        # Order by ID to return deterministically
        query += " ORDER BY id ASC LIMIT 1;"
        
        res = session.execute(text(query), params)
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except SQLAlchemyError as e:
        logger.error(f"Error in find_instrument for symbol={symbol}, broker={broker}: {e}")
        raise DatabaseException(f"Error finding instrument for symbol {symbol} from database.", original_exception=e)
    finally:
        session.close()


def is_instrument_catalog_empty() -> bool:
    """
    Checks if the instruments table in the database is empty.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("SELECT COUNT(*) FROM instruments;"))
        count = res.scalar() or 0
        return count == 0
    except SQLAlchemyError as e:
        logger.error(f"Error checking if instrument catalog is empty: {e}")
        raise DatabaseException("Error checking if instrument catalog is empty in database.", original_exception=e)
    finally:
        session.close()
