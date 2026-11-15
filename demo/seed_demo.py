"""Reset the DEMO instance: wipes the demo database and creates the demo accounts,
each with its own copy of the fictional sample portfolio (app/demo_data.py).

Run inside the demo container only:
  docker compose -f docker-compose.demo.yml exec -T networth-demo python - < demo/seed_demo.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, "/app")

# Safety: this script wipes the database. Refuse to run anywhere except the demo container.
if os.environ.get("NETWORTH_DEMO") != "1":
    sys.exit("Refusing to run: NETWORTH_DEMO=1 is not set (this is not the demo container).")

from app import db, excel  # noqa: E402
from app.auth import create_user  # noqa: E402
from app.demo_data import seed_user  # noqa: E402

ACCOUNTS = [("demo", "demo-2026-show"), ("demouser@gmail.com", "DemoUser@2026")]


def main():
    db.init_db()
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        for t in ("transactions", "valuations", "assets", "liability_updates", "liabilities",
                  "settings", "snapshots", "sessions", "users"):
            con.execute(f"DELETE FROM {t}")
        con.execute("DELETE FROM sqlite_sequence")
        for f in os.listdir(excel.DATA_DIR):
            if f.startswith("networth") and f.endswith(".xlsx"):
                os.remove(os.path.join(excel.DATA_DIR, f))
        for username, password in ACCOUNTS:
            create_user(con, username, password)
            uid = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
            seed_user(con, uid)
            excel.write_file(con, uid)
    print("Demo reset. Accounts: " + ", ".join(f"{u} / {p}" for u, p in ACCOUNTS))


main()
