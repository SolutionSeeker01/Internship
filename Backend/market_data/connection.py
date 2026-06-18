import os
import threading
from kiteconnect import KiteConnect, KiteTicker
from utils.logger import get_logger

# Set up logger for this module
logger = get_logger(__name__)

# Locks for thread-safe singleton initialization
_kite_lock = threading.Lock()

# Centralized KiteConnect shared singleton instance
_kite_client = None


class MissingCredentialsError(Exception):
    """Exception raised when required Zerodha credentials are missing from the environment."""
    pass


def get_kite() -> KiteConnect:
    """
    Returns a shared, centralized, and authenticated KiteConnect client session.
    Reuses the singleton instance after the first initialization.

    Returns:
        KiteConnect: The initialized KiteConnect client session.

    Raises:
        MissingCredentialsError: If required credentials are missing from the environment.
    """
    global _kite_client
    if _kite_client is not None:
        return _kite_client

    with _kite_lock:
        # Double-checked locking pattern for thread safety
        if _kite_client is not None:
            return _kite_client

        logger.info("Initializing centralized Zerodha KiteConnect client...")
        api_key = os.getenv("ZERODHA_API_KEY")
        access_token = os.getenv("ZERODHA_ACCESS_TOKEN")

        if not api_key or not access_token:
            error_msg = "Missing ZERODHA_API_KEY or ZERODHA_ACCESS_TOKEN environment variables."
            logger.error(error_msg)
            raise MissingCredentialsError(error_msg)

        try:
            kite = KiteConnect(api_key=api_key, timeout=10)
            kite.set_access_token(access_token)
            _kite_client = kite
            logger.info("Centralized KiteConnect client initialized successfully with timeout=10.")
            return _kite_client
        except Exception as e:
            logger.exception("Failed to initialize centralized KiteConnect client.")
            raise


def create_kws() -> KiteTicker:
    """
    Reads Zerodha credentials from environment variables, validates them,
    and returns an initialized KiteTicker instance.
    
    Expected Environment Variables:
        - ZERODHA_API_KEY: The Zerodha developer API key.
        - ZERODHA_ACCESS_TOKEN: The active session access token required for WebSocket authentication.
        
    Returns:
        KiteTicker: An initialized (but not connected) KiteTicker instance.
        
    Raises:
        MissingCredentialsError: If any of the required environment variables are missing or empty.
    """
    logger.info("Initializing Zerodha KiteTicker connection...")

    api_key = os.getenv("ZERODHA_API_KEY")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN")

    if not api_key or not access_token:
        error_msg = "Missing ZERODHA_API_KEY or ZERODHA_ACCESS_TOKEN environment variables."
        logger.error(error_msg)
        raise MissingCredentialsError(error_msg)

    try:
        kws = KiteTicker(api_key=api_key, access_token=access_token)
        logger.info("KiteTicker instance created successfully.")
        return kws
    except Exception as e:
        logger.exception("Failed to initialize KiteTicker client.")
        raise
