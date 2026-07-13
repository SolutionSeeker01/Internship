import os, sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from database.db import SessionLocal
from models.broker_account import BrokerAccount
from services.brokers.factory import BrokerFactory
from security.encryption import decrypt_value
from datetime import datetime
import pytz

session = SessionLocal()
try:
    account = session.query(BrokerAccount).first()
    if account:
        print("Account found! user_id:", account.user_id)
        print("is_connected:", account.is_connected)
        print("updated_at:", account.updated_at)
        print("updated_at tzinfo:", account.updated_at.tzinfo)
        
        api_key = decrypt_value(account.api_key)
        access_token = decrypt_value(account.access_token) if account.access_token else None
        
        broker = BrokerFactory.get_broker(
            account.broker,
            api_key=api_key,
            access_token=access_token
        )
        expired = broker.is_token_expired(account.updated_at)
        print("is_token_expired evaluates to:", expired)
        
        # Details of the computation inside is_token_expired
        from zoneinfo import ZoneInfo
        from datetime import time
        ist = ZoneInfo("Asia/Kolkata")
        now_ist = datetime.now(ist)
        print("now_ist:", now_ist)
        
        if account.updated_at.tzinfo is None:
            last_updated_ist = pytz.utc.localize(account.updated_at).astimezone(ist)
        else:
            last_updated_ist = account.updated_at.astimezone(ist)
        print("last_updated_ist:", last_updated_ist)
        days_delta = (now_ist.date() - last_updated_ist.date()).days
        print("days_delta:", days_delta)
    else:
        print("No account found in DB")
finally:
    session.close()
