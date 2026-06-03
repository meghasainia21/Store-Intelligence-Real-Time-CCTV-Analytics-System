import sqlite3

conn = sqlite3.connect("your_db_file.db")  # <-- change if needed
cur = conn.cursor()

# 1. total events
print("\nTOTAL EVENTS:")
print(cur.execute("SELECT COUNT(*) FROM events").fetchone())

# 2. sample rows
print("\nSAMPLE EVENTS:")
for row in cur.execute("SELECT store_id, event_type, timestamp FROM events LIMIT 10"):
    print(row)

# 3. store check
print("\nSTORE CHECK:")
for row in cur.execute("SELECT store_id, COUNT(*) FROM events GROUP BY store_id"):
    print(row)