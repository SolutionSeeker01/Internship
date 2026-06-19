import time
from typing import Optional, Dict, Tuple
import threading
from market_data.connection import get_kite
from utils.logger import get_logger

logger = get_logger(__name__)

# Thread-safe lock for cache access
_cache_lock = threading.Lock()

# In-memory cache for symbol LTP. Key: symbol (uppercase), Value: (ltp, epoch_seconds_timestamp)
_LTP_CACHE: Dict[str, Tuple[float, float]] = {}
CACHE_TTL_SECONDS = 30.0


def get_market_price(symbol: str) -> Optional[float]:
    """
    Authoritative helper to retrieve the last traded price (LTP) for a symbol directly from Zerodha.
    Probes exchanges (NSE first, then BSE) with built-in caching (TTL = 30 seconds).
    
    Returns:
        Optional[float]: The last traded price if found, otherwise None.
    """
    sym_upper = symbol.upper().strip()
    now = time.time()
    
    # 1. Check in-memory cache
    with _cache_lock:
        if sym_upper in _LTP_CACHE:
            cached_price, cached_time = _LTP_CACHE[sym_upper]
            if now - cached_time < CACHE_TTL_SECONDS:
                logger.debug(f"LTP cache hit for {sym_upper}: {cached_price}")
                return cached_price
            
    # 2. Cache miss - query Zerodha Kite Connect
    try:
        kite = get_kite()
        # Query both exchanges in one go to minimize network roundtrips
        query_symbols = [f"NSE:{sym_upper}", f"BSE:{sym_upper}"]
        ltp_res = kite.ltp(query_symbols)
        
        if ltp_res:
            for q_sym in query_symbols:
                if q_sym in ltp_res and ltp_res[q_sym].get("last_price") is not None:
                    price = ltp_res[q_sym]["last_price"]
                    if isinstance(price, (int, float)) and price > 0:
                        # Store in cache and return
                        with _cache_lock:
                            _LTP_CACHE[sym_upper] = (price, now)
                        logger.info(f"LTP lookup succeeded for {sym_upper}: {price} via {q_sym}")
                        return price
                        
        logger.warning(f"LTP lookup returned no valid price for {sym_upper} on NSE/BSE.")
    except Exception as e:
        logger.warning(f"Failed authoritative live market price lookup for {sym_upper}: {e}")
        
    return None
