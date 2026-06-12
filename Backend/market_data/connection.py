import os
from kiteconnect import KiteTicker
from Backend.utils.logger import get_logger

# Set up logger for this module
logger = get_logger(__name__)


class MissingCredentialsError(Exception):
    """Exception raised when required Zerodha credentials are missing from the environment."""
    pass


def create_kws() -> KiteTicker:
    """
    Reads Zerodha credentials from environment variables, validates them,
    and returns an initialized KiteTicker instance.
    
    Expected Environment Variables:
        - ZERODHA_API_KEY: The Zerodha developer API key.
        - ZERODHA_SECRET: The Zerodha developer API secret (validated but not directly passed to KiteTicker).
        - ZERODHA_ACCESS_TOKEN: The active session access token required for WebSocket authentication.
        
    Returns:
        KiteTicker: An initialized (but not connected) KiteTicker instance.
        
    Raises:
        MissingCredentialsError: If any of the required environment variables are missing or empty.
    """
    logger.info("Initializing Zerodha KiteTicker connection...")

    # 1. Read variables from the environment
    api_key = os.getenv("ZERODHA_API_KEY")
    access_token = os.getenv("ZERODHA_ACCESS_TOKEN")

    # 2. Validate environment variables
    missing_vars = []
    if not api_key:
        missing_vars.append("ZERODHA_API_KEY")
    if not access_token:
        missing_vars.append("ZERODHA_ACCESS_TOKEN")

    if missing_vars:
        error_msg = f"Missing required environment variable(s): {', '.join(missing_vars)}"
        logger.error(error_msg)
        raise MissingCredentialsError(error_msg)

    logger.debug("Zerodha credentials successfully validated.")

    # 3. Create KiteTicker instance
    try:
        # KiteTicker uses api_key and access_token for WebSocket authentication.
        # The secret is utilized during the initial HTTP handshake/session creation,
        # but validation ensures it is present for backend processes requiring it.
        kws = KiteTicker(api_key=api_key, access_token=access_token)
        logger.info("KiteTicker instance created successfully.")
        return kws
    except Exception as e:
        logger.exception("Failed to initialize KiteTicker client.")
        raise
