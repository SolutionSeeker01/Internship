import os, sys
sys.path.append('.')
from dotenv import load_dotenv
load_dotenv()
from database.db import SessionLocal
from sqlalchemy import text
session = SessionLocal()
try:
    result = session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='signals' ORDER BY ordinal_position"))
    cols = [row[0] for row in result.all()]
    print('Current signals columns:', cols)
finally:
    session.close()
