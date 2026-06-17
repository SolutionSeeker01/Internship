from pydantic import BaseModel, Field, field_validator

class WebhookSignalRequest(BaseModel):
    """
    Pydantic request schema for incoming webhook signal signals.
    Normalizes and validates fields for future multi-broker compatibility.
    """
    secret: str = Field(..., min_length=1, description="Webhook validation secret")
    action: str = Field(..., description="Action (BUY or SELL, case-insensitive)")
    symbol: str = Field(..., description="Normalized uppercase symbol (e.g. RELIANCE)")
    entry: float = Field(..., gt=0, description="Entry price level")
    sl: float = Field(..., gt=0, description="Stop loss price level")
    tf: str = Field(..., min_length=1, description="Timeframe of the signal")
    ts: int = Field(..., gt=0, description="Epoch milliseconds timestamp of signal generation")

    @field_validator('action')
    @classmethod
    def validate_action(cls, v: str) -> str:
        upper_action = v.upper()
        if upper_action not in ('BUY', 'SELL'):
            raise ValueError("Action must be either 'BUY' or 'SELL' (case-insensitive)")
        return upper_action

    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        return v.strip().upper()
