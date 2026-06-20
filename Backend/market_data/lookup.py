import time
from typing import Optional, Dict, Tuple
import threading
from market_data.connection import get_kite
from market_data.store import get_symbol_exchange_data
from utils.logger import get_logger

logger = get_logger(__name__)

class BrokerUnavailableException(Exception):
    """Exception raised when the broker service is offline or throws an error during LTP check."""
    pass

# Thread-safe lock for cache access
_cache_lock = threading.Lock()

# In-memory cache for symbol LTP. Key: symbol (uppercase), Value: (ltp, epoch_seconds_timestamp)
_LTP_CACHE: Dict[str, Tuple[float, float]] = {}
CACHE_TTL_SECONDS = 30.0


def get_market_price(symbol: str) -> Optional[float]:
    """
    Authoritative helper to retrieve the last traded price (LTP) for a symbol.
    Checks the resolved exchange (NSE/NFO/etc.) in the live cache first, then queries Zerodha dynamically.
    
    Returns:
        Optional[float]: The last traded price if found, otherwise None.
    """
    from market_data.universe import get_symbol_exchange
    sym_upper = symbol.upper().strip()
    exch_resolved = get_symbol_exchange(sym_upper)
    now = time.time()
    
    # 1. Check live memory store for resolved exchange LTP first (Fast path)
    try:
        store_data = get_symbol_exchange_data(sym_upper, exch_resolved)
        if store_data and store_data.get("ltp") is not None:
            ltp = store_data["ltp"]
            if isinstance(ltp, (int, float)) and ltp > 0:
                logger.debug(f"LTP live store hit for {sym_upper} ({exch_resolved}): {ltp}")
                return ltp
    except Exception as e:
        logger.warning(f"Error checking live store for {sym_upper} ({exch_resolved}): {e}")

    # 2. Check local TTL cache
    with _cache_lock:
        if sym_upper in _LTP_CACHE:
            cached_price, cached_time = _LTP_CACHE[sym_upper]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.debug(f"LTP TTL cache hit for {sym_upper} ({exch_resolved}): {cached_price}")
                return cached_price
            
    # 3. Cache miss - query Zerodha Kite Connect dynamically using resolved exchange
    try:
        kite = get_kite()
        query_symbol = f"{exch_resolved}:{sym_upper}"
        ltp_res = kite.ltp([query_symbol])
        
        if ltp_res and query_symbol in ltp_res and ltp_res[query_symbol].get("last_price") is not None:
            price = ltp_res[query_symbol]["last_price"]
            if isinstance(price, (int, float)) and price > 0:
                # Store in TTL cache and return
                with _cache_lock:
                    _LTP_CACHE[sym_upper] = (price, now)
                logger.info(f"Authoritative live LTP lookup succeeded for {sym_upper} ({exch_resolved}): {price}")
                return price
                        
        logger.warning(f"LTP lookup returned no valid price for {sym_upper} on {exch_resolved}.")
    except Exception as e:
        logger.warning(f"Failed authoritative live market price lookup for {sym_upper} ({exch_resolved}): {e}")
        raise BrokerUnavailableException(str(e))
        
    return None
