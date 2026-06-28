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
    Reloads all active instruments from the PostgreSQL database into the RAM cache.
    Rebuilds lookup tables atomically and thread-safely.

    Raises:
        RuntimeError: If no active instruments are found in the database.
    """
    global _TOKEN_TO_SYMBOL, _SYMBOL_TO_METADATA, _TOKEN_TO_METADATA
    logger.info("Reloading active instruments from database...")
    session = SessionLocal()
    try:
        sql = text("""
            SELECT id, symbol, token, exchange, name, segment, broker, active
            FROM instruments
            WHERE active = TRUE;
        """)
        result = session.execute(sql)
        rows = result.fetchall()

        if not rows:
            logger.warning("No active instruments found in database. Clearing cache.")
            with _lock:
                _TOKEN_TO_SYMBOL = {}
                _SYMBOL_TO_METADATA = {}
                _TOKEN_TO_METADATA = {}
            return

        new_token_to_symbol: Dict[int, str] = {}
        new_symbol_to_metadata: Dict[str, Dict[str, Any]] = {}
        new_token_to_metadata: Dict[int, Dict[str, Any]] = {}

        for row in rows:
            mapping = row._mapping
            symbol = mapping["symbol"]
            token = int(mapping["token"])

            new_token_to_symbol[token] = symbol
            meta_dict = {
                "id": symbol,  # For backward compatibility as the frontend expects key symbol as id
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

        # Update cache under lock to ensure thread safety for active readers (e.g. KiteTicker thread)
        with _lock:
            _TOKEN_TO_SYMBOL = new_token_to_symbol
            _SYMBOL_TO_METADATA = new_symbol_to_metadata
            _TOKEN_TO_METADATA = new_token_to_metadata

        logger.info(f"Successfully loaded {len(new_symbol_to_metadata)} active instruments into cache.")
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
