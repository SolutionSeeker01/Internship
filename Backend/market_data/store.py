import threading
from copy import deepcopy
from typing import Any, Dict, Optional
from Backend.utils.logger import get_logger

# Set up logging for this module
logger = get_logger(__name__)

# Internal thread-safe lock to synchronize read/write access to the store.
# Since KiteTicker updates run in a separate background thread while
# FastAPI and WebSocket clients query/read from the main thread,
# thread safety is crucial to prevent concurrent modification issues.
_store_lock = threading.Lock()

# The in-memory database holding the latest tick data per symbol.
# Key: Trading symbol (e.g., "RELIANCE")
# Value: Normalized tick data dictionary
_market_data_store: Dict[str, Dict[str, Any]] = {}


def update_market_data(symbol: str, data: Dict[str, Any]) -> None:
    """
    Updates the in-memory store with the latest market data for the given symbol.
    
    If the symbol already exists, its data is updated (or merged). Otherwise,
    a new entry is created.
    
    Args:
        symbol (str): The unified trading symbol (e.g., 'RELIANCE').
        data (Dict[str, Any]): Normalized dictionary containing tick details (ltp, volume, open, high, etc.).
    """
    with _store_lock:
        # Shallow copy is usually fine, but deepcopy protects against nested dictionary modifications.
        # Storing a copy ensures that external mutations to the input dict do not affect the store.
        _market_data_store[symbol] = deepcopy(data)
        
    logger.debug(f"Updated market data in store for symbol: {symbol}")


def get_market_data() -> Dict[str, Dict[str, Any]]:
    """
    Returns the full snapshot of the current market data.
    
    Returns:
        Dict[str, Dict[str, Any]]: A deep copy of the full market data snapshot
                                   to prevent concurrent read/write race conditions.
    """
    with _store_lock:
        return deepcopy(_market_data_store)


def get_symbol_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the latest market data for a single symbol.
    
    Args:
        symbol (str): The unified trading symbol (e.g., 'RELIANCE').
        
    Returns:
        Optional[Dict[str, Any]]: A deep copy of the symbol's market data if found,
                                  otherwise None.
    """
    with _store_lock:
        data = _market_data_store.get(symbol)
        
    if data is None:
        logger.debug(f"Symbol {symbol} requested but not present in store.")
        return None
        
    return deepcopy(data)
