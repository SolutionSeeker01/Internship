import os, sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from database.db import SessionLocal
from models.broker_account import BrokerAccount
from security.encryption import decrypt_value
from kiteconnect import KiteConnect

session = SessionLocal()
try:
    account = session.query(BrokerAccount).filter(BrokerAccount.user_id == 1).first()
    if account:
        print("Decrypting credentials...")
        api_key = decrypt_value(account.api_key)
        access_token = decrypt_value(account.access_token) if account.access_token else None
        print("API Key:", api_key)
        print("Access Token:", access_token)
        
        if access_token:
            try:
                kite = KiteConnect(api_key=api_key)
                kite.set_access_token(access_token)
                profile = kite.profile()
                print("Connection success! Profile:", profile)
            except Exception as e:
                print("Zerodha request failed:", e)
        else:
            print("Access token is None in database")
    else:
        print("Account not found")
finally:
    session.close()
