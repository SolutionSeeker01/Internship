import os
import json
from typing import Set, List, Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Locate cache file in the Backend directory
CACHE_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "universe_cache.json")

# Thread-safe in-memory cache for O(1) symbol -> metadata mapping
# Schema: { SYMBOL: { "exchange": str, "instrument_token": int } }
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
                    _UNIVERSE_CACHE = {
                        str(sym).upper().strip(): {
                            "exchange": "NSE",
                            "instrument_token": 0
                        } for sym in data
                    }
                elif isinstance(data, dict):
                    parsed_cache = {}
                    for k, v in data.items():
                        key = str(k).upper().strip()
                        if isinstance(v, dict):
                            parsed_cache[key] = {
                                "exchange": str(v.get("exchange", "NSE")).upper().strip(),
                                "instrument_token": int(v.get("instrument_token", 0))
                            }
                        else:
                            # Backward compatibility for flat value: "SYMBOL": "EXCHANGE"
                            parsed_cache[key] = {
                                "exchange": str(v).upper().strip(),
                                "instrument_token": 0
                            }
                    _UNIVERSE_CACHE = parsed_cache
                else:
                    _UNIVERSE_CACHE = {}
            logger.info(f"Successfully loaded {len(_UNIVERSE_CACHE)} instruments into UNIVERSE_CACHE from file.")
        except Exception as e:
            logger.error(f"Failed to load UNIVERSE_CACHE from file: {e}")
            _UNIVERSE_CACHE = {}
    else:
        _UNIVERSE_CACHE = {}
        logger.warning("Universe cache not found. Symbol validation fallback mode enabled.")

def persist_universe_cache() -> None:
    """
    Saves the current in-memory _UNIVERSE_CACHE state to the persisted JSON file.
    """
    try:
        with open(CACHE_FILE_PATH, "w") as f:
            json.dump(_UNIVERSE_CACHE, f, indent=4)
        logger.info(f"Successfully persisted UNIVERSE_CACHE on disk ({len(_UNIVERSE_CACHE)} instruments).")
    except Exception as e:
        logger.error(f"Failed to persist UNIVERSE_CACHE to file: {e}")

def save_universe_cache(symbols: List[str] | dict) -> None:
    """
    Persists the updated universe mapping to the JSON cache file and updates memory.
    Supports list of symbols or dict containing metadata payloads.
    """
    global _UNIVERSE_CACHE
    
    clean_cache = {}
    if isinstance(symbols, dict):
        for k, v in symbols.items():
            if not k:
                continue
            key = str(k).upper().strip()
            if isinstance(v, dict):
                clean_cache[key] = {
                    "exchange": str(v.get("exchange", "NSE")).upper().strip(),
                    "instrument_token": int(v.get("instrument_token", 0))
                }
            else:
                clean_cache[key] = {
                    "exchange": str(v).upper().strip(),
                    "instrument_token": 0
                }
    else:
        clean_cache = {
            str(sym).upper().strip(): {
                "exchange": "NSE",
                "instrument_token": 0
            } for sym in symbols if sym
        }
        
    _UNIVERSE_CACHE = clean_cache
    persist_universe_cache()

def add_symbol_to_universe(symbol: str, exchange: str, token: int) -> None:
    """
    Adds or updates a symbol in the universe cache and persists the state.
    """
    global _UNIVERSE_CACHE
    key = symbol.upper().strip()
    _UNIVERSE_CACHE[key] = {
        "exchange": exchange.upper().strip(),
        "instrument_token": int(token)
    }
    persist_universe_cache()

def remove_symbol_from_universe(symbol: str) -> None:
    """
    Removes a symbol from the universe cache and persists the state.
    """
    global _UNIVERSE_CACHE
    key = symbol.upper().strip()
    if key in _UNIVERSE_CACHE:
        del _UNIVERSE_CACHE[key]
        persist_universe_cache()

def clear_universe_cache() -> None:
    """
    Clears the universe cache in memory and removes the persisted file.
    """
    global _UNIVERSE_CACHE
    _UNIVERSE_CACHE = {}
    try:
        if os.path.exists(CACHE_FILE_PATH):
            os.remove(CACHE_FILE_PATH)
        logger.info("Successfully cleared universe cache in memory and on disk.")
    except Exception as e:
        logger.error(f"Failed to delete universe cache file: {e}")

def get_symbol_exchange(symbol: str) -> str:
    """
    Gets the exchange for a given symbol from the universe cache.
    Defaults to 'NSE' if the symbol is not in the cache.
    If the cache is empty or the symbol is missing, returns 'NFO' for FUT, CE, PE suffixes.
    """
    sym_upper = symbol.upper().strip()
    if sym_upper in _UNIVERSE_CACHE:
        return _UNIVERSE_CACHE[sym_upper]["exchange"]
    
    # Suffix fallback routing using regex to check for derivative patterns.
    import re
    if re.search(r'\d+[A-Z]*FUT$', sym_upper) or re.search(r'\d+[A-Z]*[CP]E$', sym_upper):
        return "NFO"
        
    return "NSE"

def get_instrument_token(symbol: str) -> Optional[int]:
    """
    Retrieves the numerical broker instrument token from universe cache.
    Returns None if cache is not populated or symbol is not found.
    """
    sym_upper = symbol.upper().strip()
    if sym_upper in _UNIVERSE_CACHE:
        token = _UNIVERSE_CACHE[sym_upper]["instrument_token"]
        return token if token != 0 else None
    return None

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

def symbol_exists(symbol: str) -> bool:
    """
    Checks if a symbol exists inside the cache registry.
    """
    return symbol.upper().strip() in _UNIVERSE_CACHE
