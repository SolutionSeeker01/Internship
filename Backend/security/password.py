from passlib.context import CryptContext

# Instantiate a shared CryptContext configuring bcrypt scheme
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """
    Hashes a plaintext password using the bcrypt algorithm.
    
    Args:
        password (str): The plain password.
        
    Returns:
        str: The generated password hash.
    """
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password matches its corresponding hash.
    
    Args:
        plain_password (str): The plain password to test.
        hashed_password (str): The expected password hash.
        
    Returns:
        bool: True if the password matches, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)
