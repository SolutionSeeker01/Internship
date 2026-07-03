from pydantic import BaseModel
from datetime import datetime

class HistoricalCandle(BaseModel):
    """
    Standardized schema representing a single historical candlestick.
    """
    candle_start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
