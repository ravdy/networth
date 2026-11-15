"""Authentication: accounts with scrypt password hashes + server-side sessions.

Each account has its own private portfolio. Sign-up from the browser is on by default
(NETWORTH_ALLOW_SIGNUP=0 turns it off; the very first account can always be created).

Password reset (inside the container):
    docker compose exec -it networth python -m app.auth reset [username]
List accounts:
    docker compose exec networth python -m app.auth list
"""
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta

from .db import connect, init_db

COOKIE = "nw_session"
IDLE_MINUTES = int(os.environ.get("NETWORTH_IDLE_MINUTES", "60"))
MAX_HOURS = int(os.environ.get("NETWORTH_SESSION_HOURS", "12"))
MIN_PASSWORD = 10
ALLOW_SIGNUP = os.environ.get("NETWORTH_ALLOW_SIGNUP", "1").lower() not in ("0", "false", "no", "off")
SIGNUPS_PER_HOUR = int(os.environ.get("NETWORTH_SIGNUPS_PER_HOUR", "20"))
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{2,59}$")

# scrypt parameters (~50 ms per check): N=2^15, r=8, p=1
_N, _R, _P = 2 ** 15, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=64 * 1024 * 1024, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        test = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024, dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(test, bytes.fromhex(dk))
    except (ValueError, TypeError):
        return False


def password_problem(pw: str):
    if len(pw) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if pw.lower() in ("password123", "1234567890", "qwertyuiop", "networth123"):
        return "That password is too common."
    return None


def _tok_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- users ----------

def user_count(con) -> int:
    return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def username_problem(con, username: str):
    u = username.strip()
    if not USERNAME_RE.match(u):
        return "Username: 3–60 characters, letters, numbers and . _ @ + - (an email address works)."
    if con.execute("SELECT 1 FROM users WHERE username=? COLLATE NOCASE", (u,)).fetchone():
        return "That username is taken. Pick another, or sign in."
    return None


def create_user(con, username: str, pw: str) -> int:
    return con.execute("INSERT INTO users(username, pw_hash, created_at) VALUES (?,?,?)",
                       (username.strip(), hash_password(pw), datetime.now().isoformat(timespec="seconds"))).lastrowid


_signups: list = []


def signup_allowed_now() -> bool:
    """Simple flood guard: at most SIGNUPS_PER_HOUR new accounts per hour."""
    now = time.time()
    _signups[:] = [t for t in _signups if now - t < 3600]
    return len(_signups) < SIGNUPS_PER_HOUR


def note_signup():
    _signups.append(time.time())


def check_login(con, username: str, pw: str):
    row = con.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)).fetchone()
    if not row:
        verify_password(pw, hash_password("timing-equaliser"))  # same cost whether or not the user exists
        return None
    return row["id"] if verify_password(pw, row["pw_hash"]) else None


def set_password(con, user_id: int, pw: str):
    con.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(pw), user_id))
    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))  # log out everywhere


# ---------- sessions ----------

def new_session(con, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now().isoformat(timespec="seconds")
    con.execute("INSERT INTO sessions(token_hash, user_id, created_at, last_seen) VALUES (?,?,?,?)",
                (_tok_hash(token), user_id, now, now))
    return token


def session_user(con, token: str):
    """Return the user row for a valid session (and slide its idle timer), else None."""
    if not token:
        return None
    row = con.execute(
        "SELECT s.*, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
        (_tok_hash(token),)).fetchone()
    if not row:
        return None
    now = datetime.now()
    if (now - datetime.fromisoformat(row["last_seen"]) > timedelta(minutes=IDLE_MINUTES)
            or now - datetime.fromisoformat(row["created_at"]) > timedelta(hours=MAX_HOURS)):
        con.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
        return None
    con.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now.isoformat(timespec="seconds"), row["token_hash"]))
    return row


def end_session(con, token: str):
    if token:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (_tok_hash(token),))


def purge_expired(con):
    cutoff_idle = (datetime.now() - timedelta(minutes=IDLE_MINUTES)).isoformat(timespec="seconds")
    cutoff_max = (datetime.now() - timedelta(hours=MAX_HOURS)).isoformat(timespec="seconds")
    con.execute("DELETE FROM sessions WHERE last_seen < ? OR created_at < ?", (cutoff_idle, cutoff_max))


# ---------- brute-force protection (in memory, per username) ----------

_fails: dict = {}


def locked_for(username: str) -> int:
    f = _fails.get(username.lower())
    return max(0, int(f["until"] - time.time())) if f else 0


def record_failure(username: str):
    f = _fails.setdefault(username.lower(), {"count": 0, "until": 0})
    f["count"] += 1
    if f["count"] >= 5:  # 5th failure: 30 s, then 60 s, 120 s ... capped at 15 min
        f["until"] = time.time() + min(900, 30 * 2 ** (f["count"] - 5))


def record_success(username: str):
    _fails.pop(username.lower(), None)


# ---------- CLI: password reset ----------

def _cli():
    if len(sys.argv) < 2 or sys.argv[1] not in ("reset", "list"):
        print("usage: python -m app.auth reset [username]   |   python -m app.auth list")
        sys.exit(2)
    init_db()
    with connect() as con:
        users = con.execute("SELECT id, username, created_at FROM users ORDER BY id").fetchall()
        if not users:
            print("No account yet - open the app in your browser to create one.")
            return
        if sys.argv[1] == "list":
            for u in users:
                print(f"{u['id']:>4}  {u['username']:<40} created {u['created_at']}")
            return
        if len(sys.argv) > 2:
            u = next((x for x in users if x["username"].lower() == sys.argv[2].lower()), None)
            if not u:
                print(f"No account called '{sys.argv[2]}'. Run: python -m app.auth list")
                sys.exit(1)
        elif len(users) == 1:
            u = users[0]
        else:
            print("Several accounts exist - say which one: python -m app.auth reset <username>")
            sys.exit(1)
        print(f"Resetting password for '{u['username']}'.")
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat: "):
            print("Passwords don't match.")
            sys.exit(1)
        if (p := password_problem(pw)):
            print(p)
            sys.exit(1)
        set_password(con, u["id"], pw)
        print("Password changed. All sessions were logged out.")


if __name__ == "__main__":
    _cli()
