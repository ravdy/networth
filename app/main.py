import asyncio
import base64
import calendar
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth, excel, portfolio, recommendations, report
from .catalog import ASSET_TYPE_MAP, LIABILITY_TYPE_MAP, meta
from .db import backup, connect, daily_backup_if_needed, init_db, today

STATIC = os.path.join(os.path.dirname(__file__), "static")

async def _backup_loop():
    while True:
        try:
            daily_backup_if_needed()
        except Exception as e:  # never let a backup problem stop the app
            print(f"backup failed: {e}", flush=True)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app):
    init_db()
    task = asyncio.create_task(_backup_loop())
    yield
    task.cancel()


# API docs are switched off: they would describe every endpoint to anyone who can reach the port
app = FastAPI(title="Net Worth Tracker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---------- models ----------

def _valid_date(v):
    if v in (None, ""):
        return today()
    datetime.strptime(v, "%Y-%m-%d")
    return v


class TxIn(BaseModel):
    date: Optional[str] = Field(default=None, validate_default=True)
    kind: Literal["BUY", "SELL"] = "BUY"
    amount: float = Field(ge=0)
    units: Optional[float] = None
    note: str = ""
    @field_validator("date")
    @classmethod
    def _d(cls, v):
        return _valid_date(v)


FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}


def add_months(d, n):
    m = d.month - 1 + n
    y, mo = d.year + m // 12, m % 12 + 1
    return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))


def schedule(start: str, end: Optional[str], frequency: str):
    """Dates from start, every N months, up to end (default today). Never in the future."""
    s = date.fromisoformat(start)
    e = min(date.fromisoformat(end) if end else date.today(), date.today())
    out, i = [], 0
    while True:
        d = add_months(s, i * FREQ_MONTHS[frequency])
        if d > e or len(out) >= 600:
            return out
        out.append(d.isoformat())
        i += 1


class RecurringIn(BaseModel):
    frequency: Literal["monthly", "quarterly", "half_yearly", "yearly"]
    amount: float = Field(gt=0)
    start_date: str
    end_date: Optional[str] = None
    units: Optional[float] = Field(default=None, ge=0)   # units per instalment (optional)
    note: str = ""

    @field_validator("start_date")
    @classmethod
    def _s(cls, v):
        return _valid_date(v)

    @field_validator("end_date")
    @classmethod
    def _e(cls, v):
        return _valid_date(v) if v else None


class ValuationIn(BaseModel):
    date: Optional[str] = Field(default=None, validate_default=True)
    value: float = Field(ge=0)
    @field_validator("date")
    @classmethod
    def _d(cls, v):
        return _valid_date(v)


class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str
    notes: str = ""
    purchase: Optional[TxIn] = None          # first purchase, optional on create
    current_value: Optional[float] = Field(default=None, ge=0)

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in ASSET_TYPE_MAP:
            raise ValueError("unknown asset type")
        return v


class AssetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str
    notes: str = ""

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in ASSET_TYPE_MAP:
            raise ValueError("unknown asset type")
        return v


class LiabilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str
    principal: float = Field(ge=0)
    outstanding: Optional[float] = Field(default=None, ge=0)
    interest_rate: Optional[float] = Field(default=None, ge=0, le=100)
    emi: Optional[float] = Field(default=None, ge=0)
    tenure_months: Optional[int] = Field(default=None, ge=0, le=600)
    start_date: Optional[str] = Field(default=None, validate_default=True)
    notes: str = ""
    @field_validator("start_date")
    @classmethod
    def _sd(cls, v):
        return _valid_date(v)

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in LIABILITY_TYPE_MAP:
            raise ValueError("unknown liability type")
        return v


class OutstandingIn(BaseModel):
    date: Optional[str] = Field(default=None, validate_default=True)
    outstanding: float = Field(ge=0)
    @field_validator("date")
    @classmethod
    def _d(cls, v):
        return _valid_date(v)


class SettingsIn(BaseModel):
    name: str = ""
    age: Optional[float] = Field(default=None, ge=15, le=100)
    risk_profile: Literal["conservative", "moderate", "aggressive"] = "moderate"
    monthly_expenses: Optional[float] = Field(default=None, ge=0)
    annual_income: Optional[float] = Field(default=None, ge=0)
    dependents: Optional[float] = Field(default=None, ge=0)
    tax_regime: Literal["new", "old"] = "new"


# ---------- helpers ----------

def _exists(con, table, id_):
    if not con.execute(f"SELECT 1 FROM {table} WHERE id=?", (id_,)).fetchone():
        raise HTTPException(404, f"{table[:-1]} not found")


def _asset(con, id_):
    for a in portfolio.load_assets(con):
        if a["id"] == id_:
            return a
    raise HTTPException(404, "asset not found")


# ---------- API ----------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def get_meta():
    return meta()


@app.get("/api/summary")
def get_summary():
    with connect() as con:
        return portfolio.summary(con)


@app.get("/api/assets")
def list_assets():
    with connect() as con:
        return portfolio.load_assets(con)


@app.post("/api/assets", status_code=201)
def create_asset(body: AssetIn):
    with connect() as con:
        cur = con.execute("INSERT INTO assets(name, type, notes) VALUES (?,?,?)", (body.name.strip(), body.type, body.notes))
        aid = cur.lastrowid
        if body.purchase and body.purchase.amount > 0:
            p = body.purchase
            con.execute("INSERT INTO transactions(asset_id, date, kind, amount, units, note) VALUES (?,?,?,?,?,?)",
                        (aid, p.date, "BUY", p.amount, p.units, p.note))
        if body.current_value is not None:
            con.execute("INSERT INTO valuations(asset_id, date, value) VALUES (?,?,?)", (aid, today(), body.current_value))
        portfolio.record_snapshot(con)
        return _asset(con, aid)


@app.get("/api/assets/{aid}")
def get_asset(aid: int):
    with connect() as con:
        a = _asset(con, aid)
        a["transactions"] = [dict(r) for r in con.execute(
            "SELECT * FROM transactions WHERE asset_id=? ORDER BY date DESC, id DESC", (aid,))]
        a["valuations"] = [dict(r) for r in con.execute(
            "SELECT * FROM valuations WHERE asset_id=? ORDER BY date DESC, id DESC", (aid,))]
        return a


@app.put("/api/assets/{aid}")
def update_asset(aid: int, body: AssetUpdate):
    with connect() as con:
        _exists(con, "assets", aid)
        con.execute("UPDATE assets SET name=?, type=?, notes=? WHERE id=?", (body.name.strip(), body.type, body.notes, aid))
        portfolio.record_snapshot(con)
        return _asset(con, aid)


@app.delete("/api/assets/{aid}", status_code=204)
def delete_asset(aid: int):
    with connect() as con:
        _exists(con, "assets", aid)
        con.execute("DELETE FROM assets WHERE id=?", (aid,))
        portfolio.record_snapshot(con)


@app.post("/api/assets/{aid}/transactions", status_code=201)
def add_tx(aid: int, body: TxIn):
    with connect() as con:
        _exists(con, "assets", aid)
        con.execute("INSERT INTO transactions(asset_id, date, kind, amount, units, note) VALUES (?,?,?,?,?,?)",
                    (aid, body.date, body.kind, body.amount, body.units, body.note))
        portfolio.record_snapshot(con)
        return _asset(con, aid)


@app.post("/api/assets/{aid}/transactions/recurring", status_code=201)
def add_recurring(aid: int, body: RecurringIn):
    dates = schedule(body.start_date, body.end_date, body.frequency)
    if not dates:
        raise HTTPException(400, "no payment dates between start and end (dates in the future are skipped)")
    label = {"monthly": "Monthly", "quarterly": "Quarterly", "half_yearly": "Half-yearly", "yearly": "Yearly"}[body.frequency]
    with connect() as con:
        _exists(con, "assets", aid)
        con.executemany(
            "INSERT INTO transactions(asset_id, date, kind, amount, units, note) VALUES (?,?,?,?,?,?)",
            [(aid, d, "BUY", body.amount, body.units, body.note or f"{label} payment") for d in dates])
        portfolio.record_snapshot(con)
        return {"created": len(dates), "total": round(len(dates) * body.amount, 2),
                "first": dates[0], "last": dates[-1], "asset": _asset(con, aid)}


@app.put("/api/transactions/{tid}")
def update_tx(tid: int, body: TxIn):
    with connect() as con:
        _exists(con, "transactions", tid)
        con.execute("UPDATE transactions SET date=?, kind=?, amount=?, units=?, note=? WHERE id=?",
                    (body.date, body.kind, body.amount, body.units, body.note, tid))
        portfolio.record_snapshot(con)
        return {"ok": True}


@app.delete("/api/transactions/{tid}", status_code=204)
def delete_tx(tid: int):
    with connect() as con:
        _exists(con, "transactions", tid)
        con.execute("DELETE FROM transactions WHERE id=?", (tid,))
        portfolio.record_snapshot(con)


@app.post("/api/assets/{aid}/valuations", status_code=201)
def add_valuation(aid: int, body: ValuationIn):
    with connect() as con:
        _exists(con, "assets", aid)
        con.execute("INSERT INTO valuations(asset_id, date, value) VALUES (?,?,?)", (aid, body.date, body.value))
        portfolio.record_snapshot(con)
        return _asset(con, aid)


@app.delete("/api/valuations/{vid}", status_code=204)
def delete_valuation(vid: int):
    with connect() as con:
        _exists(con, "valuations", vid)
        con.execute("DELETE FROM valuations WHERE id=?", (vid,))
        portfolio.record_snapshot(con)


@app.get("/api/liabilities")
def list_liabilities():
    with connect() as con:
        return portfolio.load_liabilities(con)


@app.post("/api/liabilities", status_code=201)
def create_liability(body: LiabilityIn):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO liabilities(name, type, principal, interest_rate, emi, tenure_months, start_date, notes) VALUES (?,?,?,?,?,?,?,?)",
            (body.name.strip(), body.type, body.principal, body.interest_rate, body.emi, body.tenure_months, body.start_date, body.notes))
        lid = cur.lastrowid
        if body.outstanding is not None and body.outstanding != body.principal:
            con.execute("INSERT INTO liability_updates(liability_id, date, outstanding) VALUES (?,?,?)",
                        (lid, today(), body.outstanding))
        portfolio.record_snapshot(con)
        return {"id": lid}


@app.get("/api/liabilities/{lid}")
def get_liability(lid: int):
    with connect() as con:
        for l in portfolio.load_liabilities(con):
            if l["id"] == lid:
                l["updates"] = [dict(r) for r in con.execute(
                    "SELECT * FROM liability_updates WHERE liability_id=? ORDER BY date DESC, id DESC", (lid,))]
                return l
        raise HTTPException(404, "liability not found")


@app.put("/api/liabilities/{lid}")
def update_liability(lid: int, body: LiabilityIn):
    with connect() as con:
        _exists(con, "liabilities", lid)
        con.execute(
            "UPDATE liabilities SET name=?, type=?, principal=?, interest_rate=?, emi=?, tenure_months=?, start_date=?, notes=? WHERE id=?",
            (body.name.strip(), body.type, body.principal, body.interest_rate, body.emi, body.tenure_months, body.start_date, body.notes, lid))
        portfolio.record_snapshot(con)
        return {"id": lid}


@app.delete("/api/liabilities/{lid}", status_code=204)
def delete_liability(lid: int):
    with connect() as con:
        _exists(con, "liabilities", lid)
        con.execute("DELETE FROM liabilities WHERE id=?", (lid,))
        portfolio.record_snapshot(con)


@app.post("/api/liabilities/{lid}/updates", status_code=201)
def add_outstanding(lid: int, body: OutstandingIn):
    with connect() as con:
        _exists(con, "liabilities", lid)
        con.execute("INSERT INTO liability_updates(liability_id, date, outstanding) VALUES (?,?,?)",
                    (lid, body.date, body.outstanding))
        portfolio.record_snapshot(con)
        return {"ok": True}


@app.delete("/api/liability-updates/{uid}", status_code=204)
def delete_outstanding(uid: int):
    with connect() as con:
        _exists(con, "liability_updates", uid)
        con.execute("DELETE FROM liability_updates WHERE id=?", (uid,))
        portfolio.record_snapshot(con)


@app.get("/api/settings")
def read_settings():
    with connect() as con:
        return portfolio.get_settings(con)


@app.put("/api/settings")
def write_settings(body: SettingsIn):
    with connect() as con:
        for k, v in body.model_dump().items():
            con.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, "" if v is None else str(v)))
        return portfolio.get_settings(con)


@app.get("/api/growth")
def get_growth(asset_id: Optional[int] = None):
    with connect() as con:
        if asset_id:
            _exists(con, "assets", asset_id)
        return portfolio.growth_series(con, asset_id)


@app.get("/api/recommendations")
def get_recommendations():
    with connect() as con:
        s = portfolio.get_settings(con)
        assets = portfolio.load_assets(con)
        liabs = portfolio.load_liabilities(con)
        summ = portfolio.summary(con)
        return recommendations.build(s, assets, liabs, summ)


TABLES = ["assets", "transactions", "valuations", "liabilities", "liability_updates", "settings", "snapshots"]


@app.get("/api/export")
def export_all():
    with connect() as con:
        data = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t}")] for t in TABLES}
    data["exported_at"] = datetime.now().isoformat(timespec="seconds")
    return data


# ---------- Excel sync ----------

class ExcelIn(BaseModel):
    data_base64: Optional[str] = None   # uploaded file; omitted = use data/networth.xlsx


def _excel_bytes(body: ExcelIn) -> bytes:
    if body.data_base64:
        return base64.b64decode(body.data_base64.split(",")[-1])
    if not os.path.exists(excel.XLSX_PATH):
        raise HTTPException(404, "No Excel file yet — create it first")
    with open(excel.XLSX_PATH, "rb") as f:
        return f.read()


@app.get("/api/excel/status")
def excel_status():
    with connect() as con:
        return excel.status(con)


@app.post("/api/excel/export")
def excel_export(force: bool = False):
    with connect() as con:
        st = excel.status(con)
        if st["pending"] and not force:
            raise HTTPException(409, "The Excel file has edits that haven't been loaded yet. "
                                     "Load them first, or overwrite to discard them.")
        excel.write_file(con)
        return excel.status(con)


@app.get("/api/excel/download")
def excel_download():
    with connect() as con:
        data = excel.workbook_bytes(con)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="networth-{today()}.xlsx"'})


@app.post("/api/excel/preview")
def excel_preview(body: ExcelIn):
    data = _excel_bytes(body)
    with connect() as con:
        try:
            changes, warnings, _ = excel.plan_changes(con, data)
        except Exception as e:  # unreadable / wrong file
            raise HTTPException(400, f"Couldn't read the Excel file: {e}")
        return {"changes": changes, "warnings": warnings}


@app.post("/api/excel/apply")
def excel_apply(body: ExcelIn):
    data = _excel_bytes(body)
    backup("before-excel-import")
    with connect() as con:
        try:
            changes, warnings, ops = excel.plan_changes(con, data)
        except Exception as e:
            raise HTTPException(400, f"Couldn't read the Excel file: {e}")
        excel.apply_ops(con, ops)
        portfolio.record_snapshot(con)
    with connect() as con:   # refresh the file so its snapshot matches the database again
        excel.write_file(con)
    return {"applied": len(changes), "warnings": warnings}


@app.middleware("http")
async def refresh_excel_after_changes(request: Request, call_next):
    """Keep data/networth.xlsx current after edits made in the app (never over unloaded Excel edits)."""
    response = await call_next(request)
    if (request.method in ("POST", "PUT", "DELETE") and request.url.path.startswith("/api/")
            and not request.url.path.startswith(("/api/excel", "/api/auth")) and response.status_code < 400):
        try:
            with connect() as con:
                if os.path.exists(excel.XLSX_PATH) and not excel.status(con)["pending"]:
                    excel.write_file(con)
        except Exception as e:  # never fail the user's request because of the Excel copy
            print(f"excel refresh skipped: {e}", flush=True)
    return response


@app.get("/api/export/docx")
def export_docx():
    with connect() as con:
        data = report.build_docx(con)
    fname = f"networth-report-{today()}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/import")
def import_all(data: dict):
    missing = [t for t in TABLES if t not in data or not isinstance(data[t], list)]
    if missing:
        raise HTTPException(400, f"backup is missing: {', '.join(missing)}")
    backup("before-import")
    with connect() as con:
        for t in reversed(TABLES):
            con.execute(f"DELETE FROM {t}")
        for t in TABLES:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            for row in data[t]:
                keys = [k for k in row if k in cols]
                if keys:
                    con.execute(f"INSERT INTO {t}({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
                                [row[k] for k in keys])
        portfolio.record_snapshot(con)
    return {"ok": True}


# ---------- frontend ----------

# ---------- authentication ----------

class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


def _login_response(request: Request, token: str, body: dict):
    r = JSONResponse(body)
    # session cookie: no max-age (gone when the browser closes), not readable by JavaScript, never sent cross-site
    r.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict", path="/",
                 secure=request.url.scheme == "https")
    return r


@app.get("/api/auth/status")
def auth_status(request: Request):
    with connect() as con:
        user = auth.session_user(con, request.cookies.get(auth.COOKIE))
        return {"configured": auth.user_count(con) > 0, "authenticated": bool(user),
                "username": user["username"] if user else None,
                "idle_minutes": auth.IDLE_MINUTES, "min_password": auth.MIN_PASSWORD}


@app.post("/api/auth/setup")
def auth_setup(body: Credentials, request: Request):
    with connect() as con:
        if auth.user_count(con) > 0:
            raise HTTPException(403, "An account already exists. Log in instead.")
        if (p := auth.password_problem(body.password)):
            raise HTTPException(400, p)
        auth.create_user(con, body.username, body.password)
        uid = auth.check_login(con, body.username, body.password)
        return _login_response(request, auth.new_session(con, uid), {"ok": True})


@app.post("/api/auth/login")
def auth_login(body: Credentials, request: Request):
    wait = auth.locked_for(body.username)
    if wait:
        raise HTTPException(429, f"Too many wrong attempts. Try again in {wait} seconds.")
    with connect() as con:
        auth.purge_expired(con)
        uid = auth.check_login(con, body.username, body.password)
        if not uid:
            auth.record_failure(body.username)
            raise HTTPException(401, "Wrong username or password.")
        auth.record_success(body.username)
        return _login_response(request, auth.new_session(con, uid), {"ok": True})


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    with connect() as con:
        auth.end_session(con, request.cookies.get(auth.COOKIE))
    r = JSONResponse({"ok": True})
    r.delete_cookie(auth.COOKIE, path="/")
    return r


@app.post("/api/auth/password")
def auth_password(body: PasswordChange, request: Request):
    with connect() as con:
        user = auth.session_user(con, request.cookies.get(auth.COOKIE))
        if not user:
            raise HTTPException(401, "Not logged in")
        name = user["username"]
        if not auth.check_login(con, name, body.current):
            raise HTTPException(400, "Current password is wrong.")
        if (p := auth.password_problem(body.new)):
            raise HTTPException(400, p)
        auth.set_password(con, user["user_id"], body.new)          # also logs out every session
        auth.record_success(name)                                  # clear any login lock-out
        return _login_response(request, auth.new_session(con, user["user_id"]), {"ok": True})


PUBLIC_PATHS = {"/login", "/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/favicon.ico"}
SECURITY_HEADERS = {
    # only this app's own scripts; no inline scripts, no external sites, no framing
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@app.middleware("http")
async def security(request: Request, call_next):
    """Runs before everything else: login check, cross-site request check, security headers."""
    path = request.url.path
    method = request.method

    # Block cross-site requests that change data: our own pages always send X-NW, which other sites can't
    # add without a CORS preflight (which this app never allows); Origin, when present, must be this app.
    if method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        same = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if request.headers.get("x-nw") != "1" or (origin and origin != same):
            return JSONResponse({"detail": "Cross-site request blocked"}, status_code=403)

    public = path in PUBLIC_PATHS or path.startswith("/static/")
    if not public:
        with connect() as con:
            user = auth.session_user(con, request.cookies.get(auth.COOKIE))
        if not user:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Not logged in"}, status_code=401)
            return RedirectResponse("/login", status_code=303)

    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if path.startswith("/api/") or path in ("/", "/login"):
        response.headers["Cache-Control"] = "no-store"   # don't keep financial data in the browser cache
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/login")
def login_page(request: Request):
    with connect() as con:
        if auth.session_user(con, request.cookies.get(auth.COOKIE)):
            return RedirectResponse("/", status_code=303)
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
