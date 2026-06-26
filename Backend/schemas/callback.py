from pydantic import BaseModel, Field, field_validator

class BrokerCallbackRequest(BaseModel):
    """
    Validates Zerodha OAuth callback request payloads sent by the frontend.
    """
    request_token: str = Field(..., min_length=1, description="Zerodha callback request token")
    state: str = Field(..., min_length=1, description="CSRF security verification state token")

    @field_validator("request_token", "state")
    @classmethod
    def clean_fields(cls, v: str) -> str:
        if v is None:
            raise ValueError("Value cannot be empty")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Value cannot be empty or only spaces")
        return cleaned


class BrokerCallbackResponse(BaseModel):
    """
    Onboarding confirmation payload sent back on successful broker validation.
    """
    message: str = Field(..., description="Onboarding confirmation message")
