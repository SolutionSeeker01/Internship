import os
from datetime import datetime, timedelta, timezone
from jose import jwt
from dotenv import load_dotenv

# Load environment variables at module initialization before reading
load_dotenv()

# Strict configuration loading - fail fast if environment values are missing
SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET environment variable is not configured")

ALGORITHM = os.getenv("JWT_ALGORITHM")
if not ALGORITHM:
    raise ValueError("JWT_ALGORITHM environment variable is not configured")

EXPIRE_MINUTES_STR = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES")
if not EXPIRE_MINUTES_STR:
    raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES environment variable is not configured")

try:
    EXPIRE_MINUTES = int(EXPIRE_MINUTES_STR)
except ValueError:
    raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be a valid integer")

def create_access_token(user_id: int, username: str, role: str) -> str:
    """
    Encodes claims and creates a signed JWT access token.
    
    Args:
        user_id (int): The unique database identifier of the user.
        username (str): The login username.
        role (str): The assigned access role of the user.
        
    Returns:
        str: The encoded JWT token.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=EXPIRE_MINUTES)
    to_encode = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    """
    Decodes a JWT token, verifying signature and expiration validation rules.
    
    Args:
        token (str): The raw encoded JWT token.
        
    Returns:
        dict: The verified claims dictionary payload.
        
    Raises:
        ExpiredSignatureError: If the token validity has expired.
        JWTError: If signature verification or decryption fails.
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
