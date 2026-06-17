from datetime import datetime
from typing import Any, Dict, Optional
import threading

# Centralized logger
from utils.logger import get_logger

logger = get_logger(__name__)

# Reentrant lock to secure high-frequency multi-threaded access from KiteTicker thread
_lock = threading.Lock()

# Dictionary to hold the active candle state per symbol
# Key: symbol (str), Value: candle dict
_active_candles: Dict[str, Dict[str, Any]] = {}

# Dictionary to track cumulative volumes to compute volume deltas
# Key: symbol (str), Value: last volume (int)
_last_cumulative_volumes: Dict[str, int] = {}


def process_tick(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Processes a normalized market tick to build and aggregate 1-minute candles.
    
    If the incoming tick falls into a new minute compared to the active candle,
    the active candle is closed, logged, and returned. A new active candle is
    then initialized.

    Args:
        data (Dict[str, Any]): Normalized tick data containing:
            - symbol (str)
            - ltp (float)
            - volume (int)
            - timestamp (str or datetime)

    Returns:
        Optional[Dict[str, Any]]: Completed 1-minute candle data if a rollover
            occurred, otherwise None.
    """
    symbol = data.get("symbol")
    ltp = data.get("ltp")

    if not symbol or ltp is None:
        return None

    try:
        ltp = float(ltp)
    except (ValueError, TypeError):
        return None

    # Parse and normalize timestamp to minute boundary (e.g. 12:01:15 -> 12:01:00)
    ts = data.get("timestamp")
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts)
        except Exception:
            dt = datetime.now()
    elif isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.now()

    minute_dt = dt.replace(second=0, microsecond=0)
    minute_str = minute_dt.isoformat()

    tick_volume = int(data.get("volume") or 0)

    with _lock:
        # Calculate volume delta
        prev_volume = _last_cumulative_volumes.get(symbol)
        _last_cumulative_volumes[symbol] = tick_volume

        volume_diff = 0
        if prev_volume is not None:
            volume_diff = max(0, tick_volume - prev_volume)

        active_candle = _active_candles.get(symbol)
        completed_candle = None

        if active_candle is not None:
            # If the tick timestamp minute differs from the active candle's start, roll over
            if active_candle["candle_start"] != minute_str:
                completed_candle = active_candle.copy()
                
                # Format start time for log presentation (HH:MM)
                try:
                    start_dt = datetime.fromisoformat(completed_candle["candle_start"])
                    time_str = start_dt.strftime("%H:%M")
                except Exception:
                    time_str = completed_candle["candle_start"]

                logger.debug(f"Closed candle: {symbol} {time_str}")
                active_candle = None

        if active_candle is None:
            # Initialize a new candle
            active_candle = {
                "symbol": symbol,
                "candle_start": minute_str,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": volume_diff,
                "trades": 1
            }
            _active_candles[symbol] = active_candle
        else:
            # Update values on the current active candle
            active_candle["high"] = max(active_candle["high"], ltp)
            active_candle["low"] = min(active_candle["low"], ltp)
            active_candle["close"] = ltp
            active_candle["volume"] += volume_diff
            active_candle["trades"] += 1

        return completed_candle
