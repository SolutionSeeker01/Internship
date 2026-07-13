import os, sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from database.db import SessionLocal
from models.broker_account import BrokerAccount
from models.user import User
from services.brokers.factory import BrokerFactory
from security.encryption import decrypt_value
import logging

logging.basicConfig(level=logging.INFO)

session = SessionLocal()
try:
    account = session.query(BrokerAccount).first()
    if account:
        print("Decrypting credentials...")
        try:
            api_key_check = decrypt_value(account.api_key)
            print("API Key decrypted successfully.")
        except Exception as e:
            print("Failed to decrypt API Key:", e)

        try:
            access_token_check = decrypt_value(account.access_token) if account.access_token else None
            print("Access Token decrypted successfully.")
        except Exception as e:
            print("Failed to decrypt Access Token:", e)

        token_expired = True
        if account.access_token:
            try:
                broker = BrokerFactory.get_broker(
                    account.broker,
                    api_key=api_key_check,
                    access_token=access_token_check
                )
                token_expired = broker.is_token_expired(account.updated_at)
                print("token_expired:", token_expired)
            except Exception as e:
                print("Error during factory/expiry check:", e)
    else:
        print("No account found")
finally:
    session.close()
