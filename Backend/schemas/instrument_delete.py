from pydantic import BaseModel, Field
from typing import List

class InstrumentDeleteTarget(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=50)
    exchange: str = Field(..., min_length=1, max_length=20)

class BulkDeleteRequest(BaseModel):
    instruments: List[InstrumentDeleteTarget] = Field(
        ...,
        min_items=1,
        max_items=100,
        description="List of instruments to be deleted, max 100 per request."
    )
