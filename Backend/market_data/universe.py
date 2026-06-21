import os
import json
from typing import Set, List
from utils.logger import get_logger

logger = get_logger(__name__)

# Locate cache file in the Backend directory
CACHE_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "universe_cache.json")

# Thread-safe in-memory cache for O(1) symbol -> exchange mapping
_UNIVERSE_CACHE: dict = {}

def load_universe_cache() -> None:
    """
    Loads the last known instrument universe from the persisted JSON cache on startup.
    If the JSON cache is missing, enters fallback mode with an empty cache.
    """
    global _UNIVERSE_CACHE
    if os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Backward compatibility for old simple set list format
                    _UNIVERSE_CACHE = {str(sym).upper().strip(): "NSE" for sym in data}
                elif isinstance(data, dict):
                    _UNIVERSE_CACHE = {str(k).upper().strip(): str(v).upper().strip() for k, v in data.items()}
                else:
                    _UNIVERSE_CACHE = {}
            logger.info(f"Successfully loaded {len(_UNIVERSE_CACHE)} instruments into UNIVERSE_CACHE from file.")
        except Exception as e:
            logger.error(f"Failed to load UNIVERSE_CACHE from file: {e}")
            _UNIVERSE_CACHE = {}
    else:
        _UNIVERSE_CACHE = {}
        logger.warning("Universe cache not found. Symbol validation fallback mode enabled.")

def save_universe_cache(symbols: List[str] | dict) -> None:
    """
    Persists the updated universe mapping to the JSON cache file and updates memory.
    Supports list of symbols (default exchange NSE) or dict of symbol -> exchange.
    """
    global _UNIVERSE_CACHE
    
    if isinstance(symbols, dict):
        clean_cache = {str(k).upper().strip(): str(v).upper().strip() for k, v in symbols.items() if k}
    else:
        clean_cache = {str(sym).upper().strip(): "NSE" for sym in symbols if sym}
        
    try:
        with open(CACHE_FILE_PATH, "w") as f:
            json.dump(clean_cache, f, indent=4)
        _UNIVERSE_CACHE = clean_cache
        logger.info(f"Successfully saved and rebuilt UNIVERSE_CACHE with {len(clean_cache)} symbols.")
    except Exception as e:
        logger.error(f"Failed to save UNIVERSE_CACHE to file: {e}")

def get_symbol_exchange(symbol: str) -> str:
    """
    Gets the exchange for a given symbol from the universe cache.
    Defaults to 'NSE' if the symbol is not in the cache.
    If the cache is empty or the symbol is missing, returns 'NFO' for FUT, CE, PE suffixes.
    """
    sym_upper = symbol.upper().strip()
    if sym_upper in _UNIVERSE_CACHE:
        return _UNIVERSE_CACHE[sym_upper]
    
    # Suffix fallback routing
    if sym_upper.endswith("FUT") or sym_upper.endswith("CE") or sym_upper.endswith("PE"):
        return "NFO"
        
    return "NSE"

def is_symbol_in_universe(symbol: str) -> bool:
    """
    Performs an O(1) check of a symbol against the universe cache.
    If fallback mode is active (empty cache), validation check is bypassed (returns True).
    """
    if not _UNIVERSE_CACHE:
        return True  # Fallback mode: allow validation if cache is empty
    return symbol.upper().strip() in _UNIVERSE_CACHE

def is_universe_cache_empty() -> bool:
    """
    Returns True if the universe cache in memory is empty, indicating fallback mode.
    """
    global _UNIVERSE_CACHE
    return len(_UNIVERSE_CACHE) == 0
