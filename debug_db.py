import sqlite3

conn = sqlite3.connect("store.db")
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("TABLES:", cur.fetchall())

cur.execute("SELECT COUNT(*) FROM events")
print("EVENT COUNT:", cur.fetchone())