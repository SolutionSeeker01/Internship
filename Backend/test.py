from security.encryption import (
    encrypt_value,
    decrypt_value
)

secret = "my_api_secret"

encrypted = encrypt_value(secret)

print(encrypted)

decrypted = decrypt_value(encrypted)

print(decrypted)