# client_strategies.py - Schemas for client strategy preferences
'use strict'

from pydantic import BaseModel, Field
from typing import Optional

class ClientStrategyPreferenceUpdate(BaseModel):
    is_active: bool = Field(..., description="Client activation status toggle")

class ClientStrategyBulkItem(BaseModel):
    strategy_id: int = Field(..., description="Target strategy ID to configure")
    is_active: bool = Field(..., description="Client activation status toggle")

class ClientStrategyPreferenceResponse(BaseModel):
    id: int
    client_id: int
    strategy_id: int
    is_active: bool

    class Config:
        from_attributes = True

class ClientStrategyResponse(BaseModel):
    strategy_id: int
    name: str
    description: Optional[str] = None
    global_active: bool
    client_active: bool

    class Config:
        from_attributes = True
