from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger
from database.defaults import DEFAULT_SYMBOLS, DEFAULT_STOCKS, DEFAULT_INDICES

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
            SET instrument_category = 'INDEX', segment = 'IND'
            WHERE UPPER(symbol) IN ('NIFTY50', 'BANKNIFTY', 'SENSEX', 'NIFTY 50', 'NIFTY BANK') 
              AND (instrument_category != 'INDEX' OR segment != 'IND');
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
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
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
    except Exception as e:
        logger.error(f"Error searching instruments with query '{query}': {e}")
        return []
    finally:
        session.close()



def get_instrument_by_symbol(symbol: str) -> dict:
    """
    Retrieves a single instrument by symbol only.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category
            FROM instruments
            WHERE UPPER(symbol) = :symbol;
        """), {"symbol": symbol.upper().strip()})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except Exception as e:
        logger.error(f"Error fetching instrument by symbol {symbol}: {e}")
        return None
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
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create instrument {symbol} ({exchange}): {e}")
        return False
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
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete instrument {symbol} ({exchange}): {e}")
        return False
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
    except Exception as e:
        session.rollback()
        logger.error(f"Failed bulk deletion transaction: {e}")
        return 0
    finally:
        session.close()



def toggle_favorite(symbol: str, exchange: str, is_favorite: bool) -> bool:
    """
    Updates the favorite status of an instrument.
    If favoriting, we also set active = TRUE.
    If unfavoriting, active is set to FALSE, unless it is a permanent dashboard default instrument.
    """
    session = SessionLocal()
    try:
        sym_upper = symbol.upper().strip()
        exch_upper = exchange.upper().strip()
        


        if is_favorite:
            sql = """
                UPDATE instruments
                SET is_favorite = :is_favorite, active = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;
            """
        else:
            if sym_upper in DEFAULT_SYMBOLS:
                # Keep active = TRUE for defaults
                sql = """
                    UPDATE instruments
                    SET is_favorite = :is_favorite, updated_at = CURRENT_TIMESTAMP
                    WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;
                """
            else:
                # Set active = FALSE for user-specific favorites
                sql = """
                    UPDATE instruments
                    SET is_favorite = :is_favorite, active = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;
                """

        result = session.execute(
            text(sql),
            {"symbol": sym_upper, "exchange": exch_upper, "is_favorite": is_favorite}
        )
        session.commit()
        if result.rowcount > 0:
            logger.info(f"Instrument '{symbol}' ({exchange}) favorite state set to {is_favorite}.")
            return True
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to update favorite state for {symbol} ({exchange}): {e}")
        return False
    finally:
        session.close()

def upsert_instruments_bulk(instruments_list: list) -> dict:
    """
    UPSERTS a list of instruments into the database.
    Updates only metadata, preserving is_favorite and active flags, 
    but ensures that permanent default dashboard instruments are always active.
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

        symbols_list_str = ", ".join(f"'{s}'" for s in DEFAULT_SYMBOLS)

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

            is_default = symbol in DEFAULT_SYMBOLS
            active_val = True if is_default else False

            delete_params.append({"symbol": symbol, "exchange": exchange})
            insert_params.append({
                "symbol": symbol,
                "token": token,
                "exchange": exchange,
                "name": name,
                "segment": segment,
                "broker": broker,
                "category": category,
                "active_val": active_val
            })

            if (symbol, exchange) in existing_set:
                updated += 1
            else:
                imported += 1
                existing_set.add((symbol, exchange))

        if delete_params:
            # Group import mapping to find conflicts where a symbol exists on a different exchange
            # Delete in a single bulk query to avoid O(N) sequential scans on the PostgreSQL table
            # Since symbols can be duplicated across exchanges in the import list itself,
            # we group them to make sure we don't have multiple entries.
            # Only DELETE instruments whose UPPER(symbol) is in our imported set, but whose UPPER(exchange) matches the conflicting one.
            # We can select the symbols and their target exchanges.
            # To do this safely and in a single query:
            # DELETE FROM instruments WHERE UPPER(symbol) = :symbol AND UPPER(exchange) != :exchange
            # can be grouped.
            symbol_to_exchange = {}
            for param in delete_params:
                symbol_to_exchange[param["symbol"]] = param["exchange"]

            symbols_to_check = list(symbol_to_exchange.keys())
            
            # Batch the conflict check in chunks of 5000 symbols to avoid query parameter limits
            chunk_size = 5000
            conflicting_ids = []
            conflicting_prefs = {}  # symbol -> (is_favorite, active)
            for i in range(0, len(symbols_to_check), chunk_size):
                chunk = symbols_to_check[i:i+chunk_size]
                res = session.execute(
                    text("SELECT id, symbol, exchange, is_favorite, active FROM instruments WHERE UPPER(symbol) IN :symbols;"),
                    {"symbols": tuple(chunk)}
                )
                for row in res.fetchall():
                    row_id = row._mapping["id"]
                    sym = row._mapping["symbol"].upper()
                    exch = row._mapping["exchange"].upper()
                    is_fav = bool(row._mapping["is_favorite"])
                    is_act = bool(row._mapping["active"])
                    if symbol_to_exchange.get(sym) != exch:
                        conflicting_ids.append(row_id)
                        # Keep track of the user preferences for this symbol
                        conflicting_prefs[sym] = (is_fav, is_act)
            
            if conflicting_ids:
                # Delete conflicting records by ID (indexed primary key scan, extremely fast)
                for i in range(0, len(conflicting_ids), chunk_size):
                    session.execute(
                        text("DELETE FROM instruments WHERE id IN :ids;"),
                        {"ids": tuple(conflicting_ids[i:i+chunk_size])}
                    )

        # Update insert_params to inherit preferences from deleted conflicting instruments
        for param in insert_params:
            sym = param["symbol"]
            if sym in conflicting_prefs:
                is_fav, is_act = conflicting_prefs[sym]
                # Inherit the favorite and active state from the replaced exchange version
                param["active_val"] = is_act or param["active_val"]
                param["is_fav_val"] = is_fav
            else:
                param["is_fav_val"] = False

        if insert_params:
            session.execute(
                text(f"""
                    INSERT INTO instruments (symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category)
                    VALUES (:symbol, :token, :exchange, :name, :segment, :broker, :active_val, :is_fav_val, :category)
                    ON CONFLICT (symbol, exchange) DO UPDATE SET
                        token = EXCLUDED.token,
                        name = EXCLUDED.name,
                        segment = EXCLUDED.segment,
                        broker = EXCLUDED.broker,
                        active = CASE WHEN EXCLUDED.symbol IN ({symbols_list_str}) THEN TRUE ELSE instruments.active END,
                        instrument_category = EXCLUDED.instrument_category,
                        updated_at = CURRENT_TIMESTAMP;
                """),
                insert_params
            )
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Bulk upsert failed: {e}")
        raise e
    finally:
        session.close()
    return {"imported": imported, "updated": updated, "skipped": skipped}

def get_favorite_instruments() -> list:
    """
    Retrieves all instruments that are active and marked as favorite.
    If no favorites exist, returns:
      - Up to 3 active index instruments (ORDER BY symbol ASC LIMIT 3)
      - Up to 10 active stock instruments (ORDER BY symbol ASC LIMIT 10)
    If no active instruments exist, returns empty list.
    """
    session = SessionLocal()
    try:
        # 1. Fetch active favorites
        result = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
            FROM instruments
            WHERE active = TRUE AND is_favorite = TRUE
            ORDER BY symbol ASC;
        """))
        rows = result.fetchall()
        favorites = [dict(row._mapping) for row in rows]
        
        if favorites:
            return favorites

        # 2. No favorites: fetch fallback indices & stocks
        result_indices = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
            FROM instruments
            WHERE active = TRUE 
              AND UPPER(instrument_category) = 'INDEX'
            ORDER BY symbol ASC
            LIMIT 3;
        """))
        indices = [dict(row._mapping) for row in result_indices.fetchall()]

        result_stocks = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at
            FROM instruments
            WHERE active = TRUE
              AND UPPER(instrument_category) = 'STOCK'
            ORDER BY symbol ASC
            LIMIT 10;
        """))
        stocks = [dict(row._mapping) for row in result_stocks.fetchall()]

        return indices + stocks

    except Exception as e:
        logger.error(f"Error fetching favorite instruments: {e}")
        return []
    finally:
        session.close()


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
    except Exception as e:
        logger.error(f"Error checking duplicate instrument: {e}")
        return {"symbol_exists": False, "token_exists": False}
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
        columns = "id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at"

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
                # 2. Query watchlist items JOIN instruments directly
                stocks_result = session.execute(text(f"""
                    SELECT i.id, i.symbol, i.token, i.exchange, i.name, i.segment, i.broker, i.active, i.is_favorite, i.instrument_category, i.created_at, i.updated_at
                    FROM instruments i
                    JOIN watchlist_items wi ON i.id = wi.instrument_id
                    WHERE wi.watchlist_id = :watchlist_id
                    ORDER BY i.symbol ASC;
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
                    WHERE active = TRUE
                      AND UPPER(instrument_category) != 'INDEX'
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

    except Exception as e:
        logger.error(f"Error fetching dashboard watchlist: {e}")
        return {
            "indices": [],
            "stocks": [],
            "view_mode": "empty",
            "selected_watchlist_id": None
        }

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
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to delete all instruments: {e}")
        raise e
    finally:
        session.close()


def get_favorites_count(category: str) -> int:
    """
    Returns the count of active favorite instruments for a given category.
    If category is 'INDEX', counts indices.
    Otherwise, counts non-INDEX favorites (STOCK, ETF, FUTURE, OPTION).
    """
    session = SessionLocal()
    try:
        if category == "INDEX":
            res = session.execute(text("""
                SELECT COUNT(*) FROM instruments 
                WHERE active = TRUE AND is_favorite = TRUE AND UPPER(instrument_category) = 'INDEX';
            """))
        else:
            res = session.execute(text("""
                SELECT COUNT(*) FROM instruments 
                WHERE active = TRUE AND is_favorite = TRUE AND UPPER(instrument_category) != 'INDEX';
            """))
        return res.scalar() or 0
    except Exception as e:
        logger.error(f"Error getting favorites count for category {category}: {e}")
        return 0
    finally:
        session.close()


def get_instrument_by_symbol_exchange(symbol: str, exchange: str) -> dict:
    """
    Retrieves a single instrument by symbol and exchange.
    """
    session = SessionLocal()
    try:
        res = session.execute(text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category
            FROM instruments
            WHERE UPPER(symbol) = :symbol AND UPPER(exchange) = :exchange;
        """), {"symbol": symbol.upper().strip(), "exchange": exchange.upper().strip()})
        row = res.fetchone()
        if row:
            return dict(row._mapping)
        return None
    except Exception as e:
        logger.error(f"Error fetching instrument {symbol} on {exchange}: {e}")
        return None
    finally:
        session.close()

