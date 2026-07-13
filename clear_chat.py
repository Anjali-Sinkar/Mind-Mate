import sqlite3
import os

db_path = os.path.join("Mental-Health-Buddy", "mental_buddy.db")

conn = sqlite3.connect(db_path)

cursor = conn.cursor()

cursor.execute("DELETE FROM chat_logs")

conn.commit()

print(f"✅ Deleted {cursor.rowcount} chat records.")

conn.close()