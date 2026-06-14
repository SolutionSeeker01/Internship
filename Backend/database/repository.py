from typing import Any, Dict
from sqlalchemy.sql import text
from Backend.database.db import SessionLocal
from Backend.utils.logger import get_logger

logger = get_logger(__name__)


def insert_candle(candle: Dict[str, Any]) -> bool:
    """
    Inserts a 1-minute aggregated candle into the PostgreSQL database.
    
    Uses parameters bind mapping and resolves duplicate entries silently via:
    ON CONFLICT (symbol, candle_start) DO NOTHING.

    Args:
        candle (Dict[str, Any]): Dictionary containing:
            - symbol (str)
            - candle_start (str or datetime)
            - open (float)
            - high (float)
            - low (float)
            - close (float)
            - volume (int)
            - trades (int)

    Returns:
        bool: True if insert transaction succeeded or resolved safely, False on failure.
    """
    sql = text("""
        INSERT INTO candles_1m
        (symbol, candle_start, open, high, low, close, volume, trades)
        VALUES (:symbol, :candle_start, :open, :high, :low, :close, :volume, :trades)
        ON CONFLICT (symbol, candle_start)
        DO NOTHING;
    """)

    session = SessionLocal()
    try:
        session.execute(sql, {
            "symbol": candle.get("symbol"),
            "candle_start": candle.get("candle_start"),
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": candle.get("close"),
            "volume": candle.get("volume"),
            "trades": candle.get("trades")
        })
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.exception(
            f"Database exception inserting candle for {candle.get('symbol')} "
            f"at time {candle.get('candle_start')}: {e}"
        )
        return False
    finally:
        session.close()


if __name__ == "__main__":
    import uuid
    import datetime

    # Create dummy testing candle data frame
    test_candle = {
        "symbol": "TEST_" + str(uuid.uuid4())[:8],
        "candle_start": datetime.datetime.now().replace(second=0, microsecond=0).isoformat(),
        "open": 1250.50,
        "high": 1260.00,
        "low": 1245.25,
        "close": 1255.80,
        "volume": 55000,
        "trades": 120
    }

    print(f"--- Triggering Database Write Manual Test ---")
    print(f"Candle Payload: {test_candle}")
    
    success = insert_candle(test_candle)
    print(f"Insertion success outcome: {success}")
