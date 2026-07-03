from pydantic import BaseModel, Field, field_validator, ConfigDict, EmailStr, model_validator
from models.user import UserRole
import re
from typing import Optional

class UserCreateRequest(BaseModel):
    """
    Validates incoming request payload for creating a new user (MASTER or CLIENT).
    Enforces standardized password complexity, email syntax, and name constraints.
    """
    fullname: str = Field(..., min_length=1, description="The user's full name")
    username: str = Field(..., min_length=1, description="The unique username")
    email: EmailStr = Field(..., description="The user's unique email address")
    password: str = Field(..., min_length=8, description="The plaintext password")
    confirm_password: str = Field(..., min_length=8, description="The password confirmation")
    role: str = Field(..., description="The role of the user: MASTER or CLIENT")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if v is None:
            raise ValueError("Email cannot be empty")
        return v.strip().lower()

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        if v is None:
            raise ValueError("Username cannot be empty")
        normalized = v.strip().lower()
        if not normalized:
            raise ValueError("Username cannot be empty or only spaces")
        if not normalized.isalnum():
            raise ValueError("Username must be alphanumeric")
        return normalized

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        upper_role = v.strip().upper()
        if upper_role not in [UserRole.MASTER.value, UserRole.CLIENT.value]:
            raise ValueError("Role must be MASTER or CLIENT")
        return upper_role

    @field_validator("fullname")
    @classmethod
    def validate_fullname(cls, v: str) -> str:
        if v is None or not v.strip():
            raise ValueError("Full Name cannot be empty")
        return v.strip().title()

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """
        Standardized password complexity check for platform registration:
        - At least 8 characters
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one numeric digit
        - At least one special character
        """
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one numeric digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "UserCreateRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class UserUpdateRequest(BaseModel):
    """
    Validates the user update payload.
    """
    fullname: str = Field(..., min_length=1, description="The user's full name")
    email: EmailStr = Field(..., description="The user's unique email address")
    role: str = Field(..., description="The role of the user: MASTER or CLIENT")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        if v is None:
            raise ValueError("Email cannot be empty")
        return v.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        upper_role = v.strip().upper()
        if upper_role not in [UserRole.MASTER.value, UserRole.CLIENT.value]:
            raise ValueError("Role must be MASTER or CLIENT")
        return upper_role

    @field_validator("fullname")
    @classmethod
    def validate_fullname(cls, v: str) -> str:
        if v is None or not v.strip():
            raise ValueError("Full Name cannot be empty")
        return v.strip().title()


class UserPasswordResetRequest(BaseModel):
    """
    Validates password reset request payload.
    """
    password: str = Field(..., min_length=8, description="The plaintext password")
    confirm_password: str = Field(..., min_length=8, description="The password confirmation")

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one numeric digit")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @model_validator(mode="after")
    def validate_passwords_match(self) -> "UserPasswordResetRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class UserStatusUpdateRequest(BaseModel):
    """
    Validates the status update payload.
    """
    is_active: bool


class UserManagementResponse(BaseModel):
    """
    Serialized profile representation of users inside user management routes.
    """
    id: int
    username: str
    email: str
    fullname: Optional[str] = None
    role: str
    is_active: bool
    email_warning: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
