from database.db import SessionLocal
from sqlalchemy.sql import text
session = SessionLocal()
res = session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).fetchall()
print("=== TABLES ===")
for row in res:
    print(row[0])

print("=== WATCHLIST_ITEMS ===")
try:
    res = session.execute(text("SELECT * FROM watchlist_items LIMIT 5")).fetchall()
    for row in res:
        print(row)
except Exception as e:
    print("No watchlist_items table or error:", e)
