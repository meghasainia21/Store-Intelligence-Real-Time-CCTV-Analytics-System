import sqlite3

conn = sqlite3.connect("store.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    store_id TEXT,
    camera_id TEXT,
    visitor_id TEXT,
    event_type TEXT,
    timestamp TEXT,
    zone_id TEXT,
    dwell_ms INTEGER,
    is_staff INTEGER,
    confidence REAL,
    queue_depth INTEGER,
    sku_zone TEXT,
    session_seq INTEGER
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS pos_transactions (
    transaction_id TEXT PRIMARY KEY,
    store_id TEXT,
    timestamp TEXT,
    basket_value_inr REAL
)
""")

conn.commit()
conn.close()

print("DB initialized successfully 🚀")