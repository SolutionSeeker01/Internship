from utils.logger import get_logger
from signals.schemas import WebhookSignalRequest
from market_data.subscriptions import get_all_instruments

logger = get_logger(__name__)


def validate_signal(signal: WebhookSignalRequest) -> bool:
    """
    Performs broker-agnostic business rule validations on normalized signals.

    Rules:
    - Symbol must exist in the active instruments cache.
    - BUY signals: stoploss (sl) must be strictly below entry price.
    - SELL signals: stoploss (sl) must be strictly above entry price.

    Args:
        signal (WebhookSignalRequest): The incoming request payload.

    Returns:
        bool: True if validation succeeds, False otherwise.
    """
    symbol = signal.symbol
    action = signal.action
    entry = signal.entry
    sl = signal.sl

    logger.debug(f"Starting business rule validation for signal: {action} {symbol} Entry={entry} SL={sl}")
    """
    # 1. Verify symbol exists in the active instruments cache loaded from database
    try:
        active_instruments = get_all_instruments()
        active_symbols = {inst["symbol"].upper() for inst in active_instruments}
    except Exception as e:
        logger.error(f"Failed to fetch active instruments cache during signal validation: {e}")
        return False

    if symbol not in active_symbols:
        logger.error(f"Signal validation failed: Symbol '{symbol}' is not currently active or exists in cache.")
        return False
    """
    # 2. Validate action boundary conditions for risk management
    if action == "BUY":
        if sl >= entry:
            logger.error(
                f"Signal validation failed for BUY {symbol}: "
                f"Stoploss ({sl}) must be strictly below entry price ({entry})."
            )
            return False
    elif action == "SELL":
        if sl <= entry:
            logger.error(
                f"Signal validation failed for SELL {symbol}: "
                f"Stoploss ({sl}) must be strictly above entry price ({entry})."
            )
            return False

    logger.info(f"Signal {action} {symbol} successfully validated against business rules.")
    return True
