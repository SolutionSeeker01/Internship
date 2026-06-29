from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class WatchlistBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="The display name of the watchlist")

class WatchlistCreate(WatchlistBase):
    pass

class WatchlistUpdate(WatchlistBase):
    pass

class WatchlistResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

class WatchlistItemAdd(BaseModel):
    instrument_id: int = Field(..., gt=0, description="The ID of the instrument to add")

class WatchlistItemResponse(BaseModel):
    id: int
    symbol: str
    exchange: str
    name: str
    token: int

    class Config:
        from_attributes = True

