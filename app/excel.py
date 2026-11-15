"""Two-way Excel sync.

export:  writes data/networth.xlsx (first account) or data/networth-user<id>.xlsx (Assets, Transactions, Liabilities, Lists, hidden _sync snapshot).
import:  reads the workbook, works out what the user changed, previews it, applies it.

Change detection is three-way: every exported value is also stored in the hidden `_sync` sheet.
A cell counts as "edited" only when it differs from that snapshot, so values that changed in the
app after the export are not overwritten by stale Excel cells. Without a snapshot (e.g. a file built
by hand) cells are compared directly with the database.
"""
import hashlib
import io
import json
import os
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import portfolio
from .catalog import ASSET_TYPE_MAP, ASSET_TYPES, LIABILITY_TYPE_MAP, LIABILITY_TYPES
from .db import DB_PATH, today

DATA_DIR = os.path.dirname(os.path.abspath(DB_PATH))


def xlsx_name(con, uid) -> str:
    """The first (original) account keeps data/networth.xlsx; every other account gets its own file."""
    first = con.execute("SELECT MIN(id) FROM users").fetchone()[0]
    return "networth.xlsx" if uid == first else f"networth-user{int(uid)}.xlsx"


def xlsx_path(con, uid) -> str:
    return os.path.join(DATA_DIR, xlsx_name(con, uid))

INR = '[>=10000000]##\\,##\\,##\\,##0;[>=100000]##\\,##\\,##0;##,##0'
DATE = "dd-mmm-yyyy"
HEAD = PatternFill("solid", fgColor="2A78D6")
EDIT = PatternFill("solid", fgColor="FFF8E1")   # editable cells
CALC = PatternFill("solid", fgColor="F3F2EE")   # formulas / read-only

ASSET_COLS = ["ID", "Asset name", "Type", "Group", "Current value (₹)", "Value as of",
              "Total invested (₹)", "Gain (₹)", "Gain %", "First purchase", "Notes", "Delete? (Y)"]
TX_COLS = ["Txn ID", "Asset ID", "Asset name", "Date", "Buy / Sell", "Amount (₹)", "Units", "Note", "Delete? (Y)"]
LIAB_COLS = ["ID", "Liability name", "Type", "Start date", "Tenure (months)", "Original amount (₹)",
             "Outstanding (₹)", "Outstanding as of", "Interest % p.a.", "EMI (₹)", "Notes", "Delete? (Y)"]

ASSET_LABEL_TO_KEY = {v["label"].lower(): k for k, v in ASSET_TYPE_MAP.items()}
LIAB_LABEL_TO_KEY = {l.lower(): k for k, l in LIABILITY_TYPES}


# ---------------------------------------------------------------- helpers

def _num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, str):
        v = v.replace(",", "").replace("₹", "").replace("%", "").strip()
    return round(float(v), 2)


def _date(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)):  # Excel serial
        return date.fromordinal(date(1899, 12, 30).toordinal() + int(v)).isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"can't read date '{s}' (use e.g. 14-Apr-2025)")


def _str(v):
    return "" if v is None else str(v).strip()


def _is_formula(v):
    return isinstance(v, str) and v.startswith("=")


def _yes(v):
    return _str(v).lower() in ("y", "yes", "delete", "x", "true")


def _norm(kind, v):
    if kind == "num":
        return None if v is None else round(float(v), 2)
    if kind == "date":
        return v or None
    return _str(v)


def _style_sheet(ws, cols, widths, editable):
    for i, name in enumerate(cols, 1):
        c = ws.cell(row=1, column=i, value=name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "B2"
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for c in row:
            c.fill = EDIT if c.column in editable else CALC


# ---------------------------------------------------------------- export

def build_workbook(con, uid) -> Workbook:
    assets = portfolio.load_assets(con, uid)
    liabs = portfolio.load_liabilities(con, uid)
    txs = [dict(r) for r in con.execute(
        "SELECT t.*, a.name AS asset_name FROM transactions t JOIN assets a ON a.id=t.asset_id "
        "WHERE a.user_id=? ORDER BY a.name, t.date, t.id", (uid,))]
    snap = []

    wb = Workbook()

    # --- Read me
    ws = wb.active
    ws.title = "Read me"
    lines = [
        ("Net Worth – Excel sync", True),
        (f"Exported {datetime.now().strftime('%d %b %Y %H:%M')}. Edit the yellow cells, save, then in the app open "
         "Settings → Excel sync → 'Load changes from Excel'. You'll see a preview before anything is applied.", False),
        ("", False),
        ("Assets sheet", True),
        ("• Change Current value + Value as of to record a new market value (adds a point to the chart).", False),
        ("• Rename, change Type (pick from the list) or Notes.", False),
        ("• New asset: add a row with no ID — fill Asset name, Type, Current value. Put its purchases in Transactions.", False),
        ("• Put Y in 'Delete?' to delete an asset (and its history).", False),
        ("Transactions sheet (purchases, payments, premiums, sales)", True),
        ("• Edit date / amount / units / note of any row.", False),
        ("• New payment: add a row with no Txn ID, write the Asset name exactly as on the Assets sheet (or its ID), "
         "Date, Buy or Sell, Amount.", False),
        ("Liabilities sheet", True),
        ("• Change Outstanding + Outstanding as of after each EMI / repayment. Edit rate, EMI, tenure, dates.", False),
        ("• New loan: row with no ID. Y in 'Delete?' removes one.", False),
        ("", False),
        ("Grey columns are calculated — changes there are ignored. Don't edit the ID columns.", False),
        ("Dates: type like 14-Apr-2025. Amounts: plain numbers (150000).", False),
    ]
    for i, (t, bold) in enumerate(lines, 1):
        c = ws.cell(row=i, column=1, value=t)
        c.font = Font(bold=bold, size=14 if i == 1 else 11)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 120

    # --- Lists (for dropdowns)
    lists = wb.create_sheet("Lists")
    lists.append(["Asset types", "Liability types", "Buy / Sell", "Delete"])
    a_labels = [l for _, _, l, _ in ASSET_TYPES]
    l_labels = [l for _, l in LIABILITY_TYPES]
    for i in range(max(len(a_labels), len(l_labels))):
        lists.append([a_labels[i] if i < len(a_labels) else None, l_labels[i] if i < len(l_labels) else None,
                      ["Buy", "Sell"][i] if i < 2 else None, "Y" if i == 0 else None])
    for col, w in zip("ABCD", (48, 34, 12, 8)):
        lists.column_dimensions[col].width = w
        lists[f"{col}1"].font = Font(bold=True)

    # --- Assets
    ws = wb.create_sheet("Assets", 1)
    ws.append(ASSET_COLS)
    for r, a in enumerate(sorted(assets, key=lambda x: (x["group"], x["name"].lower())), 2):
        ws.append([
            a["id"], a["name"], a["type_label"], a["group"], a["current_value"],
            date.fromisoformat(a["value_date"]) if a["value_date"] else None,
            f'=SUMIFS(Transactions!F:F,Transactions!B:B,A{r},Transactions!E:E,"Buy")'
            f'-SUMIFS(Transactions!F:F,Transactions!B:B,A{r},Transactions!E:E,"Sell")',
            f"=E{r}-G{r}", f'=IF(G{r}>0,H{r}/G{r},"")',
            f'=IFERROR(MINIFS(Transactions!D:D,Transactions!B:B,A{r}),"")',
            a["notes"] or "", None,
        ])
        for field, kind, val in (("name", "str", a["name"]), ("type", "str", a["type_label"]),
                                 ("current", "num", a["current_value"]), ("value_date", "date", a["value_date"]),
                                 ("notes", "str", a["notes"])):
            snap.append(("asset", a["id"], field, _norm(kind, val)))
    _style_sheet(ws, ASSET_COLS, [6, 38, 40, 14, 16, 14, 16, 14, 9, 14, 36, 10], editable={2, 3, 5, 6, 11, 12})
    for r in range(2, ws.max_row + 1):
        for c in "EGH":
            ws[f"{c}{r}"].number_format = INR
        ws[f"I{r}"].number_format = "0.0%"
        ws[f"F{r}"].number_format = DATE
        ws[f"J{r}"].number_format = DATE
    dv = DataValidation(type="list", formula1=f"=Lists!$A$2:$A${len(a_labels) + 1}", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("C2:C1000")
    ws.auto_filter.ref = f"A1:L{ws.max_row}"

    # --- Transactions
    ws = wb.create_sheet("Transactions", 2)
    ws.append(TX_COLS)
    for r, t in enumerate(txs, 2):
        ws.append([t["id"], t["asset_id"], f'=IFERROR(INDEX(Assets!B:B,MATCH(B{r},Assets!A:A,0)),"")',
                   date.fromisoformat(t["date"]), "Buy" if t["kind"] == "BUY" else "Sell",
                   t["amount"], t["units"], t["note"] or "", None])
        for field, kind, val in (("date", "date", t["date"]), ("kind", "str", t["kind"]),
                                 ("amount", "num", t["amount"]), ("units", "num", t["units"]),
                                 ("note", "str", t["note"]), ("asset_id", "num", t["asset_id"])):
            snap.append(("tx", t["id"], field, _norm(kind, val)))
    _style_sheet(ws, TX_COLS, [8, 9, 38, 14, 10, 16, 12, 34, 10], editable={3, 4, 5, 6, 7, 8, 9})
    for r in range(2, ws.max_row + 1):
        ws[f"D{r}"].number_format = DATE
        ws[f"F{r}"].number_format = INR
    dv = DataValidation(type="list", formula1="=Lists!$C$2:$C$3", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("E2:E5000")
    ws.auto_filter.ref = f"A1:I{ws.max_row}"

    # --- Liabilities
    ws = wb.create_sheet("Liabilities", 3)
    ws.append(LIAB_COLS)
    for l in liabs:
        ws.append([l["id"], l["name"], l["type_label"],
                   date.fromisoformat(l["start_date"]) if l["start_date"] else None,
                   l["tenure_months"], l["principal"], l["outstanding"],
                   date.fromisoformat(l["outstanding_date"]) if l["outstanding_date"] else None,
                   l["interest_rate"], l["emi"], l["notes"] or "", None])
        for field, kind, val in (("name", "str", l["name"]), ("type", "str", l["type_label"]),
                                 ("start_date", "date", l["start_date"]), ("tenure", "num", l["tenure_months"]),
                                 ("principal", "num", l["principal"]), ("outstanding", "num", l["outstanding"]),
                                 ("out_date", "date", l["outstanding_date"]), ("rate", "num", l["interest_rate"]),
                                 ("emi", "num", l["emi"]), ("notes", "str", l["notes"])):
            snap.append(("liab", l["id"], field, _norm(kind, val)))
    _style_sheet(ws, LIAB_COLS, [6, 32, 30, 14, 10, 16, 16, 14, 10, 12, 36, 10],
                 editable={2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12})
    for r in range(2, ws.max_row + 1):
        for c in "FGJ":
            ws[f"{c}{r}"].number_format = INR
        for c in "DH":
            ws[f"{c}{r}"].number_format = DATE
    dv = DataValidation(type="list", formula1=f"=Lists!$B$2:$B${len(l_labels) + 1}", allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("C2:C500")

    # --- hidden snapshot
    sync = wb.create_sheet("_sync")
    sync.append(["entity", "id", "field", "value"])
    for e, i, f, v in snap:
        sync.append([e, i, f, json.dumps(v)])
    sync.sheet_state = "hidden"
    return wb


def workbook_bytes(con, uid) -> bytes:
    buf = io.BytesIO()
    build_workbook(con, uid).save(buf)
    return buf.getvalue()


def write_file(con, uid) -> str:
    path = xlsx_path(con, uid)
    tmp = path + ".tmp"
    build_workbook(con, uid).save(tmp)
    os.replace(tmp, path)
    _set(con, uid, "_excel_synced_hash", _file_hash(path))
    _set(con, uid, "_excel_last_export", datetime.now().isoformat(timespec="seconds"))
    return path


def _set(con, uid, k, v):
    con.execute("INSERT INTO settings(user_id, key, value) VALUES (?,?,?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", (uid, k, v))


def _get(con, uid, k):
    r = con.execute("SELECT value FROM settings WHERE user_id=? AND key=?", (uid, k)).fetchone()
    return r["value"] if r else None


def _file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def status(con, uid):
    path = xlsx_path(con, uid)
    exists = os.path.exists(path)
    mtime = os.path.getmtime(path) if exists else None
    # "pending" = the file's contents differ from what the app last wrote, i.e. someone edited it
    pending = bool(exists and _file_hash(path) != _get(con, uid, "_excel_synced_hash"))
    return {
        "exists": exists,
        "host_path": f"data/{xlsx_name(con, uid)}",
        "modified": datetime.fromtimestamp(mtime).isoformat(timespec="seconds") if mtime else None,
        "last_export": _get(con, uid, "_excel_last_export"),
        "last_import": _get(con, uid, "_excel_last_import"),
        "pending": pending,
    }


# ---------------------------------------------------------------- import

def _rows(ws, ncols):
    for i, row in enumerate(ws.iter_rows(min_row=2, max_col=ncols, values_only=True), 2):
        if any(v not in (None, "") for v in row):
            yield i, list(row) + [None] * (ncols - len(row))


def plan_changes(con, uid, data: bytes):
    """Return (changes, warnings, ops). Nothing is written until ops are executed."""
    wb = load_workbook(io.BytesIO(data), data_only=False)
    for name in ("Assets", "Transactions", "Liabilities"):
        if name not in wb.sheetnames:
            raise ValueError(f"sheet '{name}' is missing — use a file exported from this app")

    snap = None
    if "_sync" in wb.sheetnames:
        snap = {}
        for e, i, f, v in wb["_sync"].iter_rows(min_row=2, values_only=True):
            if e:
                snap[(e, int(i), f)] = json.loads(v) if v is not None else None

    # only this user's records: every ID in the file is checked against these before anything is changed
    assets = {a["id"]: a for a in portfolio.load_assets(con, uid)}
    liabs = {l["id"]: l for l in portfolio.load_liabilities(con, uid)}
    txs = {r["id"]: dict(r) for r in con.execute(
        "SELECT t.* FROM transactions t JOIN assets a ON a.id=t.asset_id WHERE a.user_id=?", (uid,))}
    names = {a["name"].strip().lower(): a["id"] for a in assets.values()}

    changes, warnings, ops = [], [], []
    new_asset_keys = {}  # lower name -> placeholder resolved at apply time

    def edited(entity, id_, field, kind, excel_val, db_val):
        x = _norm(kind, excel_val)
        if snap is not None and (entity, id_, field) in snap:
            return x != snap[(entity, id_, field)]
        return x != _norm(kind, db_val)

    # ---------------- Assets
    for r, row in _rows(wb["Assets"], 12):
        aid, name, typ, _grp, cur, vdate, inv, _g, _gp, first, notes, dele = row
        where = f"Assets row {r}"
        try:
            aid = int(aid) if aid not in (None, "") else None
            cur = _num(cur) if not _is_formula(cur) else None
            vdate = _date(vdate)
            name = _str(name)
            if aid is not None and aid not in assets:
                warnings.append(f"{where}: asset ID {aid} no longer exists in the app — row ignored")
                continue
            if aid is not None and _yes(dele):
                changes.append({"sheet": "Assets", "action": "delete", "what": assets[aid]["name"],
                                "detail": "asset and all its history will be deleted"})
                ops.append(("sql", "DELETE FROM assets WHERE id=?", (aid,)))
                continue
            tkey = None
            if _str(typ):
                tkey = ASSET_LABEL_TO_KEY.get(_str(typ).lower()) or (_str(typ) if _str(typ) in ASSET_TYPE_MAP else None)
                if not tkey:
                    raise ValueError(f"unknown type '{typ}' — pick one from the dropdown")
            if aid is None:
                if not name:
                    continue
                if not tkey:
                    raise ValueError("new asset needs a Type")
                if name.lower() in names or name.lower() in new_asset_keys:
                    raise ValueError(f"an asset called '{name}' already exists")
                new_asset_keys[name.lower()] = True
                inv_num = _num(inv) if not _is_formula(inv) else None
                first_d = _date(first) if not _is_formula(first) else None
                detail = [ASSET_TYPE_MAP[tkey]["label"]]
                if inv_num:
                    detail.append(f"purchase ₹{inv_num:,.0f} on {first_d or today()}")
                if cur is not None:
                    detail.append(f"current value ₹{cur:,.0f}")
                changes.append({"sheet": "Assets", "action": "add", "what": name, "detail": " · ".join(detail)})
                ops.append(("new_asset", name, tkey, _str(notes), inv_num, first_d, cur, vdate))
                continue
            a = assets[aid]
            sets = {}
            if name and edited("asset", aid, "name", "str", name, a["name"]):
                sets["name"] = name
            if tkey and edited("asset", aid, "type", "str", ASSET_TYPE_MAP[tkey]["label"], a["type_label"]):
                sets["type"] = tkey
            if edited("asset", aid, "notes", "str", notes, a["notes"]):
                sets["notes"] = _str(notes)
            if sets:
                desc = ", ".join(f"{k}: {a[k] if k != 'type' else a['type_label']} → "
                                 f"{v if k != 'type' else ASSET_TYPE_MAP[v]['label']}" for k, v in sets.items())
                changes.append({"sheet": "Assets", "action": "update", "what": a["name"], "detail": desc})
                ops.append(("sql", f"UPDATE assets SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                            (*sets.values(), aid)))
            date_edited = edited("asset", aid, "value_date", "date", vdate, a["value_date"])
            if cur is not None and (edited("asset", aid, "current", "num", cur, a["current_value"]) or date_edited):
                d = (vdate if date_edited else None) or today()  # value changed but date left alone -> today
                changes.append({"sheet": "Assets", "action": "value", "what": a["name"],
                                "detail": f"current value ₹{a['current_value']:,.0f} → ₹{cur:,.0f} (as of {d})"})
                ops.append(("sql", "INSERT INTO valuations(asset_id, date, value) VALUES (?,?,?)", (aid, d, cur)))
        except (ValueError, TypeError) as e:
            warnings.append(f"{where}: {e} — row skipped")

    # ---------------- Transactions
    for r, row in _rows(wb["Transactions"], 9):
        tid, aid, aname, d, kind, amt, units, note, dele = row
        where = f"Transactions row {r}"
        try:
            tid = int(tid) if tid not in (None, "") else None
            aid = int(aid) if aid not in (None, "") else None
            d = _date(d)
            k = _str(kind).upper() or "BUY"
            if k not in ("BUY", "SELL"):
                raise ValueError("Buy / Sell must be Buy or Sell")
            amt = _num(amt)
            units = _num(units)
            if tid is not None and tid not in txs:
                warnings.append(f"{where}: transaction ID {tid} no longer exists — row ignored")
                continue
            if tid is not None and _yes(dele):
                t = txs[tid]
                changes.append({"sheet": "Transactions", "action": "delete",
                                "what": assets.get(t["asset_id"], {}).get("name", "?"),
                                "detail": f"{t['date']} {t['kind'].title()} ₹{t['amount']:,.0f}"})
                ops.append(("sql", "DELETE FROM transactions WHERE id=?", (tid,)))
                continue
            # resolve asset: ID column, else typed name (incl. assets added in this same import)
            target = None
            if aid is not None:
                if aid not in assets:
                    raise ValueError(f"asset ID {aid} not found")
                target = aid
            elif _str(aname) and not _is_formula(aname):
                n = _str(aname).lower()
                target = names.get(n) or (("new", n) if n in new_asset_keys else None)
                if target is None:
                    raise ValueError(f"no asset called '{aname}' (spelling must match the Assets sheet)")
            if tid is None:
                if amt is None:
                    continue
                if target is None:
                    raise ValueError("new transaction needs an Asset name or Asset ID")
                label = assets[target]["name"] if isinstance(target, int) else _str(aname)
                changes.append({"sheet": "Transactions", "action": "add", "what": label,
                                "detail": f"{d or today()} {k.title()} ₹{amt:,.0f}" + (f" · {note}" if _str(note) else "")})
                ops.append(("new_tx", target, d or today(), k, amt, units, _str(note)))
                continue
            t = txs[tid]
            sets = {}
            if d and edited("tx", tid, "date", "date", d, t["date"]):
                sets["date"] = d
            if edited("tx", tid, "kind", "str", k, t["kind"]):
                sets["kind"] = k
            if amt is not None and edited("tx", tid, "amount", "num", amt, t["amount"]):
                sets["amount"] = amt
            if edited("tx", tid, "units", "num", units, t["units"]):
                sets["units"] = units
            if edited("tx", tid, "note", "str", note, t["note"]):
                sets["note"] = _str(note)
            if isinstance(target, int) and edited("tx", tid, "asset_id", "num", target, t["asset_id"]):
                sets["asset_id"] = target
            if sets:
                old = f"{t['date']} {t['kind'].title()} ₹{t['amount']:,.0f}"
                changes.append({"sheet": "Transactions", "action": "update",
                                "what": assets.get(t["asset_id"], {}).get("name", "?"),
                                "detail": f"{old} → " + ", ".join(f"{k2} {v}" for k2, v in sets.items())})
                ops.append(("sql", f"UPDATE transactions SET {', '.join(k2 + '=?' for k2 in sets)} WHERE id=?",
                            (*sets.values(), tid)))
        except (ValueError, TypeError) as e:
            warnings.append(f"{where}: {e} — row skipped")

    # ---------------- Liabilities
    for r, row in _rows(wb["Liabilities"], 12):
        lid, name, typ, sd, ten, prin, out, odate, rate, emi, notes, dele = row
        where = f"Liabilities row {r}"
        try:
            lid = int(lid) if lid not in (None, "") else None
            name = _str(name)
            sd, odate = _date(sd), _date(odate)
            ten = _num(ten)
            prin, out, rate, emi = _num(prin), _num(out), _num(rate), _num(emi)
            if lid is not None and lid not in liabs:
                warnings.append(f"{where}: liability ID {lid} no longer exists — row ignored")
                continue
            if lid is not None and _yes(dele):
                changes.append({"sheet": "Liabilities", "action": "delete", "what": liabs[lid]["name"], "detail": ""})
                ops.append(("sql", "DELETE FROM liabilities WHERE id=?", (lid,)))
                continue
            tkey = None
            if _str(typ):
                tkey = LIAB_LABEL_TO_KEY.get(_str(typ).lower()) or (_str(typ) if _str(typ) in LIABILITY_TYPE_MAP else None)
                if not tkey:
                    raise ValueError(f"unknown type '{typ}' — pick one from the dropdown")
            if lid is None:
                if not name:
                    continue
                if not tkey or prin is None:
                    raise ValueError("new liability needs Type and Original amount")
                changes.append({"sheet": "Liabilities", "action": "add", "what": name,
                                "detail": f"{LIABILITY_TYPE_MAP[tkey]} · outstanding ₹{(out if out is not None else prin):,.0f}"})
                ops.append(("new_liab", name, tkey, prin, out, rate, emi, int(ten) if ten else None, sd or today(),
                            _str(notes), odate))
                continue
            l = liabs[lid]
            sets = {}
            for field, col, kind, xv, dv in (
                ("name", "name", "str", name, l["name"]),
                ("start_date", "start_date", "date", sd, l["start_date"]),
                ("tenure", "tenure_months", "num", ten, l["tenure_months"]),
                ("principal", "principal", "num", prin, l["principal"]),
                ("rate", "interest_rate", "num", rate, l["interest_rate"]),
                ("emi", "emi", "num", emi, l["emi"]),
                ("notes", "notes", "str", notes, l["notes"]),
            ):
                if edited("liab", lid, field, kind, xv, dv):
                    sets[col] = int(xv) if col == "tenure_months" and xv is not None else (_str(xv) if kind == "str" else xv)
            if tkey and edited("liab", lid, "type", "str", LIABILITY_TYPE_MAP[tkey], l["type_label"]):
                sets["type"] = tkey
            if sets.get("name") == "":
                sets.pop("name")
            if sets.get("principal") is None:
                sets.pop("principal", None)
            if sets:
                nice = {"name": "name", "type": "type", "start_date": "start date", "tenure_months": "tenure (months)",
                        "principal": "original amount", "interest_rate": "interest %", "emi": "EMI", "notes": "notes"}
                changes.append({"sheet": "Liabilities", "action": "update", "what": l["name"],
                                "detail": ", ".join(f"{nice.get(k, k)} → {v}" for k, v in sets.items())})
                ops.append(("sql", f"UPDATE liabilities SET {', '.join(k + '=?' for k in sets)} WHERE id=?",
                            (*sets.values(), lid)))
            odate_edited = edited("liab", lid, "out_date", "date", odate, l["outstanding_date"])
            if out is not None and (edited("liab", lid, "outstanding", "num", out, l["outstanding"]) or odate_edited):
                d = (odate if odate_edited else None) or today()
                changes.append({"sheet": "Liabilities", "action": "balance", "what": l["name"],
                                "detail": f"outstanding ₹{l['outstanding']:,.0f} → ₹{out:,.0f} (as of {d})"})
                ops.append(("sql", "INSERT INTO liability_updates(liability_id, date, outstanding) VALUES (?,?,?)",
                            (lid, d, out)))
        except (ValueError, TypeError) as e:
            warnings.append(f"{where}: {e} — row skipped")

    return changes, warnings, ops


def apply_ops(con, uid, ops):
    new_ids = {}
    for op in ops:
        kind = op[0]
        if kind == "sql":
            con.execute(op[1], op[2])
        elif kind == "new_asset":
            _, name, tkey, notes, inv, first_d, cur, vdate = op
            aid = con.execute("INSERT INTO assets(name, type, notes, user_id) VALUES (?,?,?,?)",
                              (name, tkey, notes, uid)).lastrowid
            new_ids[name.lower()] = aid
            if inv:
                con.execute("INSERT INTO transactions(asset_id, date, kind, amount, note) VALUES (?,?,?,?,?)",
                            (aid, first_d or today(), "BUY", inv, ""))
            if cur is not None:
                con.execute("INSERT INTO valuations(asset_id, date, value) VALUES (?,?,?)", (aid, vdate or today(), cur))
        elif kind == "new_tx":
            _, target, d, k, amt, units, note = op
            aid = new_ids[target[1]] if isinstance(target, tuple) else target
            con.execute("INSERT INTO transactions(asset_id, date, kind, amount, units, note) VALUES (?,?,?,?,?,?)",
                        (aid, d, k, amt, units, note))
        elif kind == "new_liab":
            _, name, tkey, prin, out, rate, emi, ten, sd, notes, odate = op
            lid = con.execute(
                "INSERT INTO liabilities(name, type, principal, interest_rate, emi, tenure_months, start_date, notes, user_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (name, tkey, prin, rate, emi, ten, sd, notes, uid)).lastrowid
            if out is not None and out != prin:
                con.execute("INSERT INTO liability_updates(liability_id, date, outstanding) VALUES (?,?,?)",
                            (lid, odate or today(), out))
    _set(con, uid, "_excel_last_import", datetime.now().isoformat(timespec="seconds"))
