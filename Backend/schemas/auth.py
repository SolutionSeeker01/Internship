from pydantic import BaseModel, Field, field_validator, ConfigDict

class LoginRequest(BaseModel):
    """
    Validates incoming credentials submitted from the login form.
    """
    username: str = Field(..., min_length=1, description="The unique username")
    password: str = Field(..., min_length=1, description="The plaintext password")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        # Strip leading/trailing whitespaces and convert to lowercase
        if v is None:
            raise ValueError("Username cannot be empty")
        normalized = v.strip().lower()
        if not normalized:
            raise ValueError("Username cannot be empty or only spaces")
        return normalized


class UserResponse(BaseModel):
    """
    Serialized profile representation of the authenticated user.
    """
    id: int
    username: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """
    Payload containing the generated JWT and authenticated user context.
    """
    access_token: str
    token_type: str = Field(default="bearer")
    user: UserResponse
