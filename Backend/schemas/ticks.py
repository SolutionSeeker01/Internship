from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class NormalizedTick(BaseModel):
    """
    Standardized schema representing a normalized real-time market tick.
    Specifically excludes broker-specific instrument tokens.
    """
    key: str  # Format: "EXCHANGE:SYMBOL", e.g. "NSE:RELIANCE"
    symbol: str
    exchange: str
    ltp: float = 0.0
    change: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: datetime
