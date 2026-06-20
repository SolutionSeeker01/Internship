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
        existing_res = session.execute(text("SELECT symbol, exchange FROM instruments;"))
        existing_set = {
            (row._mapping["symbol"].upper(), row._mapping["exchange"].upper())
            for row in existing_res.fetchall()
        }

        symbols_list_str = ", ".join(f"'{s}'" for s in DEFAULT_SYMBOLS)

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

            # Delete any conflicting instrument with the same symbol but a different exchange
            session.execute(
                text("DELETE FROM instruments WHERE UPPER(symbol) = :symbol AND UPPER(exchange) != :exchange;"),
                {"symbol": symbol, "exchange": exchange}
            )

            session.execute(
                text(f"""
                    INSERT INTO instruments (symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category)
                    VALUES (:symbol, :token, :exchange, :name, :segment, :broker, :active_val, FALSE, :category)
                    ON CONFLICT (symbol, exchange) DO UPDATE SET
                        token = EXCLUDED.token,
                        name = EXCLUDED.name,
                        segment = EXCLUDED.segment,
                        broker = EXCLUDED.broker,
                        active = CASE WHEN EXCLUDED.symbol IN ({symbols_list_str}) THEN TRUE ELSE instruments.active END,
                        instrument_category = EXCLUDED.instrument_category,
                        updated_at = CURRENT_TIMESTAMP;
                """),
                {
                    "symbol": symbol,
                    "token": token,
                    "exchange": exchange,
                    "name": name,
                    "segment": segment,
                    "broker": broker,
                    "category": category,
                    "active_val": active_val
                }
            )
            if (symbol, exchange) in existing_set:
                updated += 1
            else:
                imported += 1
                existing_set.add((symbol, exchange))
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



def get_dashboard_watchlist() -> dict:
    """
    Returns the instruments the dashboard should render, with independent
    favorite/fallback logic for indices and stocks.

    Fallback uses curated priority lists to ensure the default dashboard
    shows useful, well-known instruments instead of obscure ones.

    Response structure:
        {
            "indices": [...],
            "stocks":  [...],
            "view_mode": {
                "indices": "favorites" | "fallback" | "empty",
                "stocks":  "favorites" | "fallback" | "empty"
            }
        }
    """
    SEARCH_INDICES = [
        "NIFTY50", "NIFTY 50", "BANKNIFTY", "NIFTY BANK", "SENSEX"
    ]

    session = SessionLocal()
    try:
        columns = "id, symbol, token, exchange, name, segment, broker, active, is_favorite, instrument_category, created_at, updated_at"

        # ── Indices (strictly category = 'INDEX') ────────────────
        fav_indices_result = session.execute(text(f"""
            SELECT {columns}
            FROM instruments
            WHERE active = TRUE
              AND UPPER(instrument_category) = 'INDEX'
              AND is_favorite = TRUE
            ORDER BY symbol ASC;
        """))
        fav_indices = [dict(row._mapping) for row in fav_indices_result.fetchall()]

        if fav_indices:
            indices = fav_indices
            indices_mode = "favorites"
        else:
            # Fallback: query by priority-ordered default index symbols
            if SEARCH_INDICES:
                placeholders = ", ".join([f":idx_{i}" for i in range(len(SEARCH_INDICES))])
                params = {f"idx_{i}": sym for i, sym in enumerate(SEARCH_INDICES)}
                fallback_indices_result = session.execute(text(f"""
                    SELECT {columns}
                    FROM instruments
                    WHERE active = TRUE
                      AND UPPER(instrument_category) = 'INDEX'
                      AND UPPER(symbol) IN ({placeholders})
                """), params)
                fallback_map = {}
                for row in fallback_indices_result.fetchall():
                    row_dict = dict(row._mapping)
                    fallback_map[row_dict["symbol"].upper()] = row_dict
                
                # Assemble in the requested priority order, preferring exact or space-spaced match
                fallback_indices = []
                
                # 1. NIFTY50 / NIFTY 50
                if "NIFTY50" in fallback_map:
                    fallback_indices.append(fallback_map["NIFTY50"])
                elif "NIFTY 50" in fallback_map:
                    fallback_indices.append(fallback_map["NIFTY 50"])
                    
                # 2. BANKNIFTY / NIFTY BANK
                if "BANKNIFTY" in fallback_map:
                    fallback_indices.append(fallback_map["BANKNIFTY"])
                elif "NIFTY BANK" in fallback_map:
                    fallback_indices.append(fallback_map["NIFTY BANK"])
                    
                # 3. SENSEX
                if "SENSEX" in fallback_map:
                    fallback_indices.append(fallback_map["SENSEX"])
            else:
                fallback_indices = []

            if fallback_indices:
                indices = fallback_indices
                indices_mode = "fallback"
            else:
                indices = []
                indices_mode = "empty"

        # ── Stocks & Others (strictly category != 'INDEX') ────────
        fav_stocks_result = session.execute(text(f"""
            SELECT {columns}
            FROM instruments
            WHERE active = TRUE
              AND UPPER(instrument_category) != 'INDEX'
              AND is_favorite = TRUE
            ORDER BY symbol ASC;
        """))
        fav_stocks = [dict(row._mapping) for row in fav_stocks_result.fetchall()]

        if fav_stocks:
            stocks = fav_stocks
            stocks_mode = "favorites"
        else:
            # Fallback: query by priority-ordered default stock symbols
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
                fallback_stocks = [fallback_map[s.upper()] for s in DEFAULT_STOCKS if s.upper() in fallback_map]
            else:
                fallback_stocks = []

            if fallback_stocks:
                stocks = fallback_stocks
                stocks_mode = "fallback"
            else:
                stocks = []
                stocks_mode = "empty"

        return {
            "indices": indices,
            "stocks": stocks,
            "view_mode": {
                "indices": indices_mode,
                "stocks": stocks_mode
            }
        }

    except Exception as e:
        logger.error(f"Error fetching dashboard watchlist: {e}")
        return {
            "indices": [],
            "stocks": [],
            "view_mode": {
                "indices": "empty",
                "stocks": "empty"
            }
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

