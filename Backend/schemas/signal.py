# signal.py - Response schemas for Signal Details API

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class SignalResponse(BaseModel):
    """
    Schema representing a persisted trading signal row.
    """
    id: int
    signal_uuid: UUID
    action: str
    symbol: str
    entry: float
    stoploss: float
    timeframe: str
    signal_timestamp: int
    status: str
    validation_status: Optional[str] = None
    validation_reason: Optional[str] = None
    validated_at: Optional[datetime] = None
    t1: Optional[float] = None
    t2: Optional[float] = None
    t3: Optional[float] = None
    strategy_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SignalTargetDetail(BaseModel):
    """
    Schema representing a targeted client record joined with their username.
    """
    client_id: int
    username: str
    status: str
    skip_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SignalSummary(BaseModel):
    """
    Schema representing aggregated target summary statistics.
    """
    total: int = Field(..., description="Total clients evaluated for this signal alert")
    ready: int = Field(..., description="Number of clients marked READY to execute")
    skipped: int = Field(..., description="Number of clients marked SKIPPED")


class SignalDetailsResponse(BaseModel):
    """
    Unified API response payload containing the signal, summary stats, and target list.
    """
    signal: SignalResponse
    summary: SignalSummary
    targets: List[SignalTargetDetail]
