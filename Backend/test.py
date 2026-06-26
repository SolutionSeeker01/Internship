from security.jwt_handler import (
    create_access_token,
    decode_access_token
)

token = create_access_token(
    user_id=1,
    username="admin",
    role="MASTER"
)

print(token)

payload = decode_access_token(token)

print(payload)
