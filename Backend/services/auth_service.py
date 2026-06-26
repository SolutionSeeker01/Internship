from typing import Optional
from database.db import SessionLocal
from models.user import User
from security.password import verify_password

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
