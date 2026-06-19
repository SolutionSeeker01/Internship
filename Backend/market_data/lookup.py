import time
from typing import Optional, Dict, Tuple
import threading
from market_data.connection import get_kite
from market_data.store import get_symbol_exchange_data
from utils.logger import get_logger

logger = get_logger(__name__)

# Thread-safe lock for cache access
_cache_lock = threading.Lock()

# In-memory cache for symbol LTP. Key: symbol (uppercase), Value: (ltp, epoch_seconds_timestamp)
_LTP_CACHE: Dict[str, Tuple[float, float]] = {}
CACHE_TTL_SECONDS = 30.0


def get_market_price(symbol: str) -> Optional[float]:
    """
    Authoritative helper to retrieve the last traded price (LTP) for a symbol.
    Strictly checks the NSE exchange in the live cache first, then queries Zerodha only for NSE.
    
    Returns:
        Optional[float]: The last traded price if found on NSE, otherwise None.
    """
    sym_upper = symbol.upper().strip()
    now = time.time()
    
    # 1. Check live memory store for NSE LTP first (Fast path)
    try:
        store_data = get_symbol_exchange_data(sym_upper, "NSE")
        if store_data and store_data.get("ltp") is not None:
            ltp = store_data["ltp"]
            if isinstance(ltp, (int, float)) and ltp > 0:
                logger.debug(f"LTP live store hit for {sym_upper} (NSE): {ltp}")
                return ltp
    except Exception as e:
        logger.warning(f"Error checking live store for {sym_upper} (NSE): {e}")

    # 2. Check local TTL cache (NSE only)
    with _cache_lock:
        if sym_upper in _LTP_CACHE:
            cached_price, cached_time = _LTP_CACHE[sym_upper]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.debug(f"LTP TTL cache hit for {sym_upper} (NSE): {cached_price}")
                return cached_price
            
    # 3. Cache miss - query Zerodha Kite Connect strictly for NSE
    try:
        kite = get_kite()
        query_symbol = f"NSE:{sym_upper}"
        ltp_res = kite.ltp([query_symbol])
        
        if ltp_res and query_symbol in ltp_res and ltp_res[query_symbol].get("last_price") is not None:
            price = ltp_res[query_symbol]["last_price"]
            if isinstance(price, (int, float)) and price > 0:
                # Store in TTL cache and return
                with _cache_lock:
                    _LTP_CACHE[sym_upper] = (price, now)
                logger.info(f"Authoritative live LTP lookup succeeded for {sym_upper} (NSE): {price}")
                return price
                        
        logger.warning(f"LTP lookup returned no valid price for {sym_upper} on NSE.")
    except Exception as e:
        logger.warning(f"Failed authoritative live market price lookup for {sym_upper} (NSE): {e}")
        
    return None
