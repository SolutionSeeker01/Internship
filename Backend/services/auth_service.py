from typing import Optional
from database.db import SessionLocal
from models.user import User, UserRole
from models.broker_account import BrokerAccount
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
    Validates that no other MASTER user has an active connected broker session.
    Provides a fail-fast validation for user experience before attempting connection changes.
    """
    active_session = session.query(BrokerAccount).join(
        User, User.id == BrokerAccount.user_id
    ).filter(
        User.role == UserRole.MASTER,
        BrokerAccount.is_connected == True,
        BrokerAccount.user_id != current_user_id
    ).first()

    if active_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Another MASTER account is already active. Only one active trading session is allowed at any time."
        )
