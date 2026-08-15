import os
import sqlite3

db = sqlite3.connect(os.environ.get("DATABASE", "/opt/eduflow/data/app.db"))
for username, display_name, role, last_login_at in db.execute(
    "SELECT username, display_name, role, last_login_at FROM users ORDER BY role, username"
):
    print(f"{username}|{display_name}|{role}|{last_login_at or 'never'}")
