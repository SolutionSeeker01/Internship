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
    """Exception raised when required Zerodha credentials are missing."""
    pass


def get_kite() -> KiteConnect:
    """
    Returns the shared, centralized, and authenticated KiteConnect client session.
    Reuses the singleton instance after initialization.

    Returns:
        KiteConnect: The initialized KiteConnect client session.

    Raises:
        MissingCredentialsError: If client has not been dynamically initialized yet.
    """
    global _kite_client
    if _kite_client is not None:
        return _kite_client

    with _kite_lock:
        if _kite_client is not None:
            return _kite_client

        error_msg = "KiteConnect client has not been dynamically initialized. Please complete broker connection onboarding first."
        logger.error(error_msg)
        raise MissingCredentialsError(error_msg)


def create_kite_client(api_key: str, access_token: str) -> KiteConnect:
    """
    Dynamically initializes, caches, and returns the centralized KiteConnect shared singleton.

    Args:
        api_key (str): The Zerodha developer API key.
        access_token (str): The active session access token.

    Returns:
        KiteConnect: The initialized KiteConnect client session.
    """
    global _kite_client
    with _kite_lock:
        logger.info("Initializing centralized Zerodha KiteConnect client dynamically...")
        try:
            kite = KiteConnect(api_key=api_key, timeout=30)
            kite.set_access_token(access_token)
            _kite_client = kite
            logger.info("Centralized KiteConnect client initialized successfully with timeout=30.")
            return _kite_client
        except Exception:
            logger.exception("Failed to initialize centralized KiteConnect client dynamically.")
            raise


def create_kws(api_key: str, access_token: str) -> KiteTicker:
    """
    Returns an initialized (but not connected) KiteTicker instance using supplied parameters.

    Args:
        api_key (str): The Zerodha developer API key.
        access_token (str): The active session access token required for WebSocket authentication.

    Returns:
        KiteTicker: An initialized KiteTicker instance.
    """
    logger.info("Initializing Zerodha KiteTicker connection dynamically...")
    try:
        kws = KiteTicker(api_key=api_key, access_token=access_token)
        logger.info("KiteTicker instance created successfully dynamically.")
        return kws
    except Exception:
        logger.exception("Failed to initialize KiteTicker client dynamically.")
        raise


def reset_connection_state() -> None:
    """
    Clears cached KiteConnect shared singleton instance thread-safely.
    """
    global _kite_client
    with _kite_lock:
        logger.info("Resetting cached Zerodha KiteConnect client singleton state.")
        _kite_client = None
