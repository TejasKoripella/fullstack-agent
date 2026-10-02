import sqlite3

db = sqlite3.connect("data/jarvis.db")

columns = {
    row[1]
    for row in db.execute("PRAGMA table_info(preferences)")
}

if "updated_at" not in columns:
    db.execute(
        "ALTER TABLE preferences "
        "ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"
    )
    print("Added preferences.updated_at")
else:
    print("preferences.updated_at already exists")

db.commit()
db.close()

print("MEMORY DATABASE MIGRATION COMPLETE")
