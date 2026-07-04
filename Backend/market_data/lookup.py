import time
from typing import Optional, Dict, Tuple
import threading

from market_data.store import get_symbol_exchange_data
from utils.logger import get_logger

logger = get_logger(__name__)

class BrokerUnavailableException(Exception):
    """Exception raised when the broker service is offline or throws an error during LTP check."""
    pass

class InvalidSymbolException(Exception):
    """Exception raised when the broker explicitly indicates the symbol is invalid."""
    pass

# Thread-safe lock for cache access
_cache_lock = threading.Lock()

# In-memory cache for symbol LTP. Key: symbol (uppercase), Value: (ltp, epoch_seconds_timestamp)
_LTP_CACHE: Dict[str, Tuple[float, float]] = {}
CACHE_TTL_SECONDS = 30.0


def get_master_broker():
    """
    Returns the currently active master broker client from the feed runner,
    avoiding database queries and key decryption overhead.
    """
    from market_data.kite_client import get_active_broker_client
    return get_active_broker_client()


def get_market_price(symbol: str) -> Optional[float]:
    """
    Authoritative helper to retrieve the last traded price (LTP) for a symbol.
    Checks the resolved exchange (NSE/NFO/etc.) in the live cache first, then queries resolved Master broker.
    
    Returns:
        Optional[float]: The last traded price if found, otherwise None.
    """
    from database.instrument_repository import find_instrument
    sym_upper = symbol.upper().strip()
    
    # Resolve exchange from PostgreSQL first
    inst = find_instrument(sym_upper)
    if inst and inst.get("exchange"):
        exch_resolved = inst["exchange"].upper().strip()
    else:
        # Fallback to derivative suffix check matching previous get_symbol_exchange behavior
        import re
        if re.search(r'\d+[A-Z]*FUT$', sym_upper) or re.search(r'\d+[A-Z]*[CP]E$', sym_upper):
            exch_resolved = "NFO"
        else:
            exch_resolved = "NSE"
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
            
    # 3. Cache miss - query active Master Broker dynamically using resolved exchange
    try:
        broker = get_master_broker()
        if not broker:
            raise BrokerUnavailableException("Master broker instance unavailable.")

        query_symbol = f"{exch_resolved}:{sym_upper}"
        ltp_res = broker.get_ltp([query_symbol])
        
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
        # Check if the exception represents an invalid symbol from the broker
        try:
            from kiteconnect.exceptions import InputException
            if isinstance(e, InputException) or "invalid" in str(e).lower() or "not found" in str(e).lower():
                logger.warning(f"Broker rejected symbol {sym_upper} as invalid: {e}")
                raise InvalidSymbolException(str(e))
        except ImportError:
            # Fallback if kiteconnect is not installed in the current environment
            if "invalid" in str(e).lower() or "not found" in str(e).lower():
                raise InvalidSymbolException(str(e))
        
        logger.warning(f"Failed authoritative live market price lookup for {sym_upper} ({exch_resolved}): {e}")
        raise BrokerUnavailableException(str(e))
        
    return None
