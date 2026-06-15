from typing import Any, Dict, List
from sqlalchemy.sql import text
from database.db import SessionLocal
from utils.logger import get_logger

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


def get_candles(symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Queries the candles_1m table for the latest candles of a given symbol,
    ordered chronologically (oldest to newest).

    Args:
        symbol (str): Symbol to query (e.g. 'RELIANCE').
        limit (int): Maximum number of records to retrieve.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries representing candle rows.
    """
    sql = text("""
        SELECT
            symbol,
            candle_start,
            open,
            high,
            low,
            close,
            volume,
            trades
        FROM candles_1m
        WHERE symbol = :symbol
        ORDER BY candle_start DESC
        LIMIT :limit;
    """)

    session = SessionLocal()
    try:
        result = session.execute(sql, {"symbol": symbol, "limit": limit})
        candles = []
        for row in result:
            candle_start = row[1]
            if hasattr(candle_start, "isoformat"):
                candle_start_str = candle_start.isoformat()
            else:
                candle_start_str = str(candle_start)

            candles.append({
                "symbol": row[0],
                "candle_start": candle_start_str,
                "open": float(row[2]) if row[2] is not None else 0.0,
                "high": float(row[3]) if row[3] is not None else 0.0,
                "low": float(row[4]) if row[4] is not None else 0.0,
                "close": float(row[5]) if row[5] is not None else 0.0,
                "volume": int(row[6]) if row[6] is not None else 0,
                "trades": int(row[7]) if row[7] is not None else 0,
            })
        
        # Reverse to oldest -> newest chronological order
        candles.reverse()
        return candles
    except Exception as e:
        logger.exception(f"Database exception retrieving candles for {symbol}: {e}")
        return []
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
