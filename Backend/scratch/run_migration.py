from database.signal_repository import init_db
init_db()
print("Migration complete")

from database.db import SessionLocal
from sqlalchemy import text
s = SessionLocal()
r = s.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='signals' ORDER BY ordinal_position"))
print("Signals columns after migration:", [row[0] for row in r.all()])
s.close()
