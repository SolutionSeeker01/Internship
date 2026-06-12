from typing import Any, Dict, List, Optional
from Backend.utils.logger import get_logger

# Set up logging for this module
logger = get_logger(__name__)

# Static list of instruments defined for V1
# Keys are the standard unified symbols used in the application.
# Value contains the Zerodha Kite metadata (token, exchange, symbol, segment).
# Hand-picked correct instrument tokens from Zerodha's instrument master list.
_INSTRUMENTS_METADATA: Dict[str, Dict[str, Any]] = {
    "NIFTY50": {
        "symbol": "NIFTY 50",
        "token": 256265,
        "exchange": "NSE",
        "name": "Nifty 50 Index",
        "segment": "INDICES",
    },
    "BANKNIFTY": {
        "symbol": "NIFTY BANK",
        "token": 260105,
        "exchange": "NSE",
        "name": "Nifty Bank Index",
        "segment": "INDICES",
    },
    "SENSEX": {
        "symbol": "SENSEX",
        "token": 265,
        "exchange": "BSE",
        "name": "BSE Sensex Index",
        "segment": "INDICES",
    },
    "RELIANCE": {
        "symbol": "RELIANCE",
        "token": 738561,
        "exchange": "NSE",
        "name": "RELIANCE INDUSTRIES LTD",
        "segment": "NSE-EQ",
    },
    "HDFCBANK": {
        "symbol": "HDFCBANK",
        "token": 341249,
        "exchange": "NSE",
        "name": "HDFC BANK LTD",
        "segment": "NSE-EQ",
    },
    "ICICIBANK": {
        "symbol": "ICICIBANK",
        "token": 1270529,
        "exchange": "NSE",
        "name": "ICICI BANK LTD",
        "segment": "NSE-EQ",
    },
    "BHARTIARTL": {
        "symbol": "BHARTIARTL",
        "token": 2714625,
        "exchange": "NSE",
        "name": "BHARTI AIRTEL LTD",
        "segment": "NSE-EQ",
    },
    "INFY": {
        "symbol": "INFY",
        "token": 408065,
        "exchange": "NSE",
        "name": "INFOSYS LTD",
        "segment": "NSE-EQ",
    },
    "TCS": {
        "symbol": "TCS",
        "token": 2953217,
        "exchange": "NSE",
        "name": "TATA CONSULTANCY SERVICES LTD",
        "segment": "NSE-EQ",
    },
    "HINDUNILVR": {
        "symbol": "HINDUNILVR",
        "token": 356865,
        "exchange": "NSE",
        "name": "HINDUSTAN UNILEVER LTD",
        "segment": "NSE-EQ",
    },
    "BAJFINANCE": {
        "symbol": "BAJFINANCE",
        "token": 81153,
        "exchange": "NSE",
        "name": "BAJAJ FINANCE LTD",
        "segment": "NSE-EQ",
    },
}

# Pre-populate token-to-symbol lookup table for efficient O(1) reverse search.
# Example: 738561 -> "RELIANCE"
# Using the key as the application-level symbol name (e.g., RELIANCE).
_TOKEN_TO_SYMBOL: Dict[int, str] = {
    info["token"]: key for key, info in _INSTRUMENTS_METADATA.items()
}


def get_tokens() -> List[int]:
    """
    Returns a list of integer instrument tokens for all subscribed instruments.
    
    This list is passed directly to Zerodha KiteTicker for subscription updates.
    
    Returns:
        List[int]: List of Kite instrument tokens.
    """
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
    symbol = _TOKEN_TO_SYMBOL.get(token)
    if not symbol:
        logger.warning(f"Lookup failed: Instrument token {token} not found in active subscriptions.")
    return symbol


def get_all_instruments() -> List[Dict[str, Any]]:
    """
    Returns full metadata for all configured instruments.
    
    This function is helpful for the frontend or initial client sync, providing the
    entire list of configured instruments including exchange, description, and token information.
    
    Returns:
        List[Dict[str, Any]]: List of dictionaries containing instrument details.
    """
    logger.debug("Retrieving metadata for all subscribed instruments.")
    return [
        {
            "id": key,
            "symbol": info["symbol"],
            "token": info["token"],
            "exchange": info["exchange"],
            "name": info["name"],
            "segment": info["segment"],
        }
        for key, info in _INSTRUMENTS_METADATA.items()
    ]
