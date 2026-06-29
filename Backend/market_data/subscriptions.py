from typing import Any, Dict, List, Optional
import threading
from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger

# Set up logging for this module
logger = get_logger(__name__)

# Thread-safety lock for cache access and reload operations
_lock = threading.Lock()

# In-memory caches for O(1) runtime lookups
_TOKEN_TO_SYMBOL: Dict[int, str] = {}
_SYMBOL_TO_METADATA: Dict[str, Dict[str, Any]] = {}
_TOKEN_TO_METADATA: Dict[int, Dict[str, Any]] = {}


def reload_instruments() -> None:
    """
    Reloads the subscription universe from PostgreSQL into the RAM cache.
    The universe is computed as the Union of:
      1. All instruments present in all user watchlists.
      2. Default dashboard stock fallback symbols.
      3. Available indices.

    Uniqueness is strictly enforced using instrument 'token' as the key.
    """
    global _TOKEN_TO_SYMBOL, _SYMBOL_TO_METADATA, _TOKEN_TO_METADATA
    logger.info("Reloading subscription universe from database...")
    
    from database.defaults import DEFAULT_STOCKS
    
    session = SessionLocal()
    try:
        # 1. Fetch dynamic indices (UPPER(instrument_category) = 'INDEX')
        index_sql = text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active
            FROM instruments
            WHERE UPPER(instrument_category) = 'INDEX';
        """)
        index_rows = session.execute(index_sql).fetchall()
        
        # 2. Fetch default dashboard fallback stocks
        default_stock_rows = []
        if DEFAULT_STOCKS:
            stk_placeholders = ", ".join([f":stk_{i}" for i in range(len(DEFAULT_STOCKS))])
            stk_params = {f"stk_{i}": sym for i, sym in enumerate(DEFAULT_STOCKS)}
            stk_sql = text(f"""
                SELECT id, symbol, token, exchange, name, segment, broker, active
                FROM instruments
                WHERE UPPER(symbol) IN ({stk_placeholders})
                  AND UPPER(instrument_category) != 'INDEX';
            """)
            default_stock_rows = session.execute(stk_sql, stk_params).fetchall()
        
        # 3. Fetch all watchlist instruments
        watchlist_sql = text("""
            SELECT i.id, i.symbol, i.token, i.exchange, i.name, i.segment, i.broker, i.active
            FROM instruments i
            JOIN watchlist_items wi ON i.id = wi.instrument_id;
        """)
        watchlist_rows = session.execute(watchlist_sql).fetchall()

        # Combine sets, maintaining metrics for logging
        unique_instruments = {}
        index_count = 0
        default_stocks_count = 0
        watchlist_count = 0

        # Process indices
        for row in index_rows:
            mapping = row._mapping
            token = int(mapping["token"])
            if token not in unique_instruments:
                unique_instruments[token] = mapping
                index_count += 1

        # Process default stocks
        for row in default_stock_rows:
            mapping = row._mapping
            token = int(mapping["token"])
            if token not in unique_instruments:
                unique_instruments[token] = mapping
                default_stocks_count += 1

        # Process watchlist items
        for row in watchlist_rows:
            mapping = row._mapping
            token = int(mapping["token"])
            if token not in unique_instruments:
                unique_instruments[token] = mapping
                watchlist_count += 1

        if not unique_instruments:
            logger.warning("WARNING: No instruments available for subscription. Clearing cache.")
            with _lock:
                _TOKEN_TO_SYMBOL = {}
                _SYMBOL_TO_METADATA = {}
                _TOKEN_TO_METADATA = {}
            return

        new_token_to_symbol: Dict[int, str] = {}
        new_symbol_to_metadata: Dict[str, Dict[str, Any]] = {}
        new_token_to_metadata: Dict[int, Dict[str, Any]] = {}

        for token, mapping in unique_instruments.items():
            symbol = mapping["symbol"]
            new_token_to_symbol[token] = symbol
            meta_dict = {
                "id": symbol,
                "symbol": symbol,
                "token": token,
                "exchange": mapping["exchange"],
                "name": mapping["name"],
                "segment": mapping["segment"],
                "broker": mapping["broker"],
                "active": bool(mapping["active"]),
            }
            new_symbol_to_metadata[symbol] = meta_dict
            new_token_to_metadata[token] = meta_dict

        # Update cache under lock to ensure thread safety
        with _lock:
            _TOKEN_TO_SYMBOL = new_token_to_symbol
            _SYMBOL_TO_METADATA = new_symbol_to_metadata
            _TOKEN_TO_METADATA = new_token_to_metadata

        logger.info(
            f"Reloaded subscription universe.\n"
            f"    Indices subscribed: {index_count}\n"
            f"    Default fallback stocks subscribed: {default_stocks_count}\n"
            f"    Watchlist instruments subscribed: {watchlist_count}\n"
            f"    Total unique subscriptions: {len(unique_instruments)}"
        )
        rebuild_universe_cache()
    except Exception as e:
        logger.error(f"Error loading instruments from database: {e}")
        raise
    finally:
        session.close()



def rebuild_universe_cache() -> None:
    """
    Utility helper that pulls all database instruments and recreates
    the universe_cache.json payload containing symbol metadata mappings.
    """
    try:
        from database.instrument_repository import get_all_instruments
        from market_data.universe import save_universe_cache
        instruments = get_all_instruments()
        mapping = {
            inst["symbol"]: {
                "exchange": inst["exchange"],
                "instrument_token": inst["token"]
            } for inst in instruments
        }
        save_universe_cache(mapping)
        logger.info(f"Successfully rebuilt universe_cache.json from database with {len(mapping)} instruments.")
    except Exception as e:
        logger.error(f"Failed to rebuild universe_cache.json: {e}")

def load_instruments() -> None:
    """
    Loads active instruments into RAM. Typically called once at startup.
    """
    reload_instruments()
    rebuild_universe_cache()


def get_tokens() -> List[int]:
    """
    Returns a list of integer instrument tokens for all subscribed instruments.
    This list is passed directly to Zerodha KiteTicker for subscription updates.

    Returns:
        List[int]: List of Kite instrument tokens.
    """
    with _lock:
        tokens = list(_TOKEN_TO_SYMBOL.keys())
    logger.debug(f"Retrieved {len(tokens)} instrument tokens for subscription.")
    return tokens


def get_symbol(token: int) -> Optional[str]:
    """
    Looks up and returns the corresponding trading symbol/key for a given instrument token.
    This reverse lookup is essential during real-time tick processing to map numerical
    tokens from incoming Kite ticker updates back to application symbols.

    Args:
        token (int): The numerical Zerodha instrument token.

    Returns:
        Optional[str]: The key/symbol (e.g., 'RELIANCE') if found, otherwise None.
    """
    with _lock:
        symbol = _TOKEN_TO_SYMBOL.get(token)
    if not symbol:
        logger.warning(f"Lookup failed: Instrument token {token} not found in active subscriptions.")
    return symbol


def get_instrument_metadata(token: int) -> Optional[Dict[str, Any]]:
    """
    Returns full metadata for an active instrument by its Zerodha token from RAM cache.
    """
    with _lock:
        return _TOKEN_TO_METADATA.get(token)


def get_all_instruments() -> List[Dict[str, Any]]:
    """
    Returns full metadata for all configured instruments from RAM.

    Returns:
        List[Dict[str, Any]]: List of dictionaries containing instrument details.
    """
    logger.debug("Retrieving metadata for all subscribed instruments.")
    with _lock:
        # Return a list of dict copies to prevent modification of external references
        return [dict(info) for info in _SYMBOL_TO_METADATA.values()]
