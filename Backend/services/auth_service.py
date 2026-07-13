from typing import Optional
from database.db import SessionLocal
from models.user import User, UserRole
from models.broker_account import BrokerAccount
from models.platform_state import PlatformState
from security.password import verify_password
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

def authenticate_user(username: str, password: str) -> Optional[User]:
    """
    Authenticates a user against database credentials.
    
    Checks existence of username case-insensitively using normalized lowercase matching,
    verifies the password hash, and checks if the user account is active.
    
    Args:
        username (str): The login username.
        password (str): The plaintext password to verify.
        
    Returns:
        User: The authenticated User ORM object if successful, None otherwise.
    """
    session = SessionLocal()
    try:
        # Find user by username using strict normalized lowercase match
        normalized_username = username.strip().lower()
        user = session.query(User).filter(
            User.username == normalized_username
        ).first()
        
        if not user:
            return None
            
        # Verify password hash
        if not verify_password(password, user.password_hash):
            return None
            
        # Verify user active status
        if not user.is_active:
            return None
            
        return user
    finally:
        session.close()


def enforce_single_active_master(session: Session, current_user_id: int) -> None:
    """
    Validates that the current user holds the active platform lock.
    """
    user = session.query(User).filter(User.id == current_user_id).first()
    if not user or user.role != UserRole.MASTER:
        return

    state = session.query(PlatformState).filter(PlatformState.id == 1).first()
    if not state or state.active_master_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not currently own the active platform session."
        )
