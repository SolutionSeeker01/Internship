from pydantic import BaseModel, Field, field_validator

class BrokerSetupRequest(BaseModel):
    """
    Validates Zerodha API Key and Secret registration payloads.
    """
    api_key: str = Field(..., min_length=1, description="Zerodha Developer API Key")
    api_secret: str = Field(..., min_length=1, description="Zerodha Developer API Secret")

    @field_validator("api_key", "api_secret")
    @classmethod
    def clean_fields(cls, v: str) -> str:
        if v is None:
            raise ValueError("Value cannot be empty")
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Value cannot be empty or only spaces")
        return cleaned


class BrokerSetupResponse(BaseModel):
    """
    Onboarding confirmation message sent to frontend.
    """
    message: str = Field(..., description="Setup confirmation message")
