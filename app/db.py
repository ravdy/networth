import os
import sqlite3
from contextlib import contextmanager
from datetime import date

DB_PATH = os.environ.get("NETWORTH_DB", os.path.join(os.path.dirname(__file__), "..", "data", "networth.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (date('now'))
);

-- Every purchase (BUY) or sale/redemption (SELL) of an asset
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id  INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('BUY','SELL')),
    amount    REAL NOT NULL CHECK (amount >= 0),
    units     REAL,
    note      TEXT DEFAULT ''
);

-- Market value updates; latest one is the asset's current value
CREATE TABLE IF NOT EXISTS valuations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id  INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    value     REAL NOT NULL CHECK (value >= 0)
);

CREATE TABLE IF NOT EXISTS liabilities (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    type           TEXT NOT NULL,
    principal      REAL NOT NULL DEFAULT 0,
    interest_rate  REAL,
    emi            REAL,
    start_date     TEXT,
    tenure_months  INTEGER,
    notes          TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS liability_updates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    liability_id  INTEGER NOT NULL REFERENCES liabilities(id) ON DELETE CASCADE,
    date          TEXT NOT NULL,
    outstanding   REAL NOT NULL CHECK (outstanding >= 0)
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- One row per day, refreshed on every change -> net worth history chart
CREATE TABLE IF NOT EXISTS snapshots (
    date         TEXT PRIMARY KEY,
    assets       REAL NOT NULL,
    liabilities  REAL NOT NULL
);

-- login (passwords stored only as salted scrypt hashes)
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- server-side sessions; only a SHA-256 of the cookie token is stored
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    last_seen   TEXT NOT NULL
);
"""


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)
        # migrations for databases created by earlier versions
        cols = {r[1] for r in con.execute("PRAGMA table_info(liabilities)")}
        if "tenure_months" not in cols:
            con.execute("ALTER TABLE liabilities ADD COLUMN tenure_months INTEGER")


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def today() -> str:
    return date.today().isoformat()


# ---------- backups ----------
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
KEEP_BACKUPS = int(os.environ.get("NETWORTH_KEEP_BACKUPS", "30"))


def backup(tag: str = "daily") -> str:
    """Consistent copy of the live database (SQLite online-backup API)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"networth-{today()}-{tag}.db" if tag == "daily" else \
        f"networth-{date.today().isoformat()}-{tag}-{os.urandom(3).hex()}.db"
    dest = os.path.join(BACKUP_DIR, name)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    _prune()
    return dest


def daily_backup_if_needed():
    if not os.path.exists(os.path.join(BACKUP_DIR, f"networth-{today()}-daily.db")):
        backup("daily")


def _prune():
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("networth-") and f.endswith(".db"))
    for f in files[:-KEEP_BACKUPS]:
        os.remove(os.path.join(BACKUP_DIR, f))
