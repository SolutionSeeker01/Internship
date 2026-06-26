import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Ensure environment variables are loaded at startup
load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError("ENCRYPTION_KEY environment variable is not configured")

try:
    # Initialize Fernet cipher engine using the key
    cipher_suite = Fernet(ENCRYPTION_KEY.encode("utf-8"))
except Exception as e:
    raise ValueError(f"Invalid ENCRYPTION_KEY format: {e}")

def encrypt_value(plain_text: str) -> str:
    """
    Encrypts a plaintext string.
    
    Args:
        plain_text (str): The plaintext string to encrypt.
        
    Returns:
        str: The Fernet ciphertext string.
    """
    if plain_text is None:
        raise ValueError("Plaintext cannot be None")
        
    plain_bytes = plain_text.encode("utf-8")
    cipher_bytes = cipher_suite.encrypt(plain_bytes)
    return cipher_bytes.decode("utf-8")

def decrypt_value(cipher_text: str) -> str:
    """
    Decrypts a Fernet ciphertext string.
    
    Args:
        cipher_text (str): The Fernet ciphertext string to decrypt.
        
    Returns:
        str: The decrypted plaintext string.
    """
    if cipher_text is None:
        raise ValueError("Ciphertext cannot be None")
        
    cipher_bytes = cipher_text.encode("utf-8")
    plain_bytes = cipher_suite.decrypt(cipher_bytes)
    return plain_bytes.decode("utf-8")
