import threading
from copy import deepcopy
from typing import Any, Dict, Optional
from utils.logger import get_logger

# Set up logging for this module
logger = get_logger(__name__)

# Internal thread-safe lock to synchronize read/write access to the store.
_store_lock = threading.Lock()

# The in-memory database holding the latest tick data per symbol key.
# Key: "EXCHANGE:SYMBOL" (str, e.g. "NSE:RELIANCE")
# Value: Normalized tick data dictionary
_market_data_store: Dict[str, Dict[str, Any]] = {}


def update_market_data(key: str, data: Dict[str, Any]) -> None:
    """
    Updates the in-memory store with the latest market data for the given EXCHANGE:SYMBOL key.
    """
    with _store_lock:
        _market_data_store[key] = deepcopy(data)
        
    logger.debug(f"Updated market data in store for key: {key}")


def get_market_data() -> Dict[str, Dict[str, Any]]:
    """
    Returns the full snapshot of the current market data.
    """
    with _store_lock:
        return deepcopy(_market_data_store)


def get_symbol_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the latest market data for a single symbol (prefers NSE).
    """
    symbol_upper = symbol.upper().strip()
    with _store_lock:
        # First pass: try to find NSE
        for data in _market_data_store.values():
            if str(data.get("symbol") or "").upper().strip() == symbol_upper and \
               str(data.get("exchange") or "").upper().strip() == "NSE":
                return deepcopy(data)
        # Second pass: fallback to any exchange
        for data in _market_data_store.values():
            if str(data.get("symbol") or "").upper().strip() == symbol_upper:
                return deepcopy(data)
    return None


def get_symbol_exchange_data(symbol: str, exchange: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the latest market data matching both symbol and exchange.
    """
    symbol_upper = symbol.upper().strip()
    exchange_upper = exchange.upper().strip()
    key = f"{exchange_upper}:{symbol_upper}"
    with _store_lock:
        if key in _market_data_store:
            return deepcopy(_market_data_store[key])
    return None
