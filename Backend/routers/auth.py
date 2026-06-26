from fastapi import APIRouter, HTTPException, status, Depends
from schemas.auth import LoginRequest, LoginResponse, UserResponse
from services.auth_service import authenticate_user
from security.jwt_handler import create_access_token
from dependencies.auth import get_current_user
from models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(payload: LoginRequest):
    """
    Authenticates user credentials and issues a signed JWT access token.
    """
    # Verify username and password against database records
    user = authenticate_user(payload.username, payload.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # Generate signed JWT token incorporating user claims
    # user.role is Enum type, we export its raw string value using .value
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role.value
    )
    
    # Return explicit schema-driven Pydantic response model
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user
    )

@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Returns the authenticated user details for the active session.
    """
    return current_user
