from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose.exceptions import JWTError

from database.db import SessionLocal
from models.user import User
from models.broker_account import BrokerAccount
from security.jwt_handler import decode_access_token

# Initialize OAuth2 password bearer scheme pointing to our login endpoint
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    Dependency to authenticate and retrieve the currently logged-in user.
    
    Args:
        token (str): The extracted Bearer token from authorization header.
        
    Returns:
        User: The authenticated User ORM model instance.
        
    Raises:
        HTTPException: If token is expired, invalid, or matching user is missing.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode and verify the cryptographic signature of the token
        payload = decode_access_token(token)
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    session = SessionLocal()
    try:
        # Query matching user record from database
        user = session.query(User).filter(User.id == int(user_id_str)).first()
        if user is None:
            raise credentials_exception
            
        # Verify that the user account has not been disabled
        if not user.is_active:
            raise credentials_exception
            
        # Dynamically query database for connected broker account to retrieve actual active broker
        account = session.query(BrokerAccount).filter(
            BrokerAccount.user_id == user.id,
            BrokerAccount.is_connected == True
        ).first()
        user.active_broker = account.broker if account else "ZERODHA"
            
        return user
    except ValueError:
        raise credentials_exception
    finally:
        session.close()
