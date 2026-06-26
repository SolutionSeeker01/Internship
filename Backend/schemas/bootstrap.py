import enum
from pydantic import BaseModel, Field

class BootstrapState(str, enum.Enum):
    """
    Enum representing the next required action in the user application state machine.
    """
    BROKER_SETUP_REQUIRED = "BROKER_SETUP_REQUIRED"
    BROKER_AUTH_REQUIRED = "BROKER_AUTH_REQUIRED"
    FULLY_READY = "FULLY_READY"


class BootstrapResponse(BaseModel):
    """
    Response schema indicating the current system onboarding status.
    """
    state: BootstrapState = Field(..., description="The next logical routing state of the client")
