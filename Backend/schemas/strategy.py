# strategy.py - Pydantic Schemas for Strategy entities
'use strict'

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class StrategyBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="The unique name of the strategy")
    description: Optional[str] = Field(None, max_length=500, description="Detailed strategy description")

class StrategyCreate(StrategyBase):
    pass

class StrategyUpdate(StrategyBase):
    pass

class StrategyStatusUpdate(BaseModel):
    is_active: bool = Field(..., description="Active/inactive status toggle")

class StrategyResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
