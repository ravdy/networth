"""Portfolio computations: current values, gains, XIRR, allocation, snapshots."""
from collections import defaultdict
from datetime import date

from .catalog import ASSET_TYPE_MAP, CATEGORIES, GROUP_ORDER, LIABILITY_TYPE_MAP, weights_for
from .db import today


def xirr(cashflows):
    """cashflows: list of (date, amount); outflows negative. Returns annual rate or None."""
    if len(cashflows) < 2:
        return None
    if not any(a < 0 for _, a in cashflows) or not any(a > 0 for _, a in cashflows):
        return None
    d0 = min(d for d, _ in cashflows)
    if (max(d for d, _ in cashflows) - d0).days < 1:
        return None

    def npv(r):
        return sum(a / (1 + r) ** ((d - d0).days / 365.0) for d, a in cashflows)

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return mid


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def load_assets(con, uid):
    assets = [dict(r) for r in con.execute("SELECT * FROM assets WHERE user_id=? ORDER BY id", (uid,))]
    txs = defaultdict(list)
    for r in con.execute("SELECT t.* FROM transactions t JOIN assets a ON a.id=t.asset_id "
                         "WHERE a.user_id=? ORDER BY t.date, t.id", (uid,)):
        txs[r["asset_id"]].append(dict(r))
    vals = defaultdict(list)
    for r in con.execute("SELECT v.* FROM valuations v JOIN assets a ON a.id=v.asset_id "
                         "WHERE a.user_id=? ORDER BY v.date, v.id", (uid,)):
        vals[r["asset_id"]].append(dict(r))

    out = []
    for a in assets:
        t = txs[a["id"]]
        v = vals[a["id"]]
        bought = sum(x["amount"] for x in t if x["kind"] == "BUY")
        sold = sum(x["amount"] for x in t if x["kind"] == "SELL")
        units = sum((x["units"] or 0) * (1 if x["kind"] == "BUY" else -1) for x in t)
        invested = bought - sold

        if v:
            last = v[-1]
            # transactions recorded after the last valuation adjust the current value
            later = sum(
                (x["amount"] if x["kind"] == "BUY" else -x["amount"])
                for x in t if x["date"] > last["date"]
            )
            current = max(0.0, last["value"] + later)
            value_date = last["date"]
        else:
            current = max(0.0, invested)
            value_date = t[-1]["date"] if t else a["created_at"]

        flows = [(_d(x["date"]), -x["amount"] if x["kind"] == "BUY" else x["amount"]) for x in t]
        flows.append((date.today(), current))
        rate = xirr(flows)

        meta = ASSET_TYPE_MAP.get(a["type"], {"label": a["type"], "group": "Other"})
        out.append({
            **a,
            "type_label": meta["label"],
            "group": meta["group"],
            "weights": weights_for(a["type"]),
            "invested": round(invested, 2),
            "current_value": round(current, 2),
            "gain": round(current - invested, 2),
            "gain_pct": round((current - invested) / invested * 100, 2) if invested > 0 else None,
            "xirr": round(rate * 100, 2) + 0.0 if rate is not None else None,
            "units": round(units, 4) if units else None,
            "avg_buy_price": round(invested / units, 4) if units > 0 and invested > 0 else None,
            "current_price": round(current / units, 4) if units > 0 else None,
            "value_date": value_date,
            "first_date": t[0]["date"] if t else a["created_at"],
            "tx_count": len(t),
        })
    return out


def load_liabilities(con, uid):
    rows = [dict(r) for r in con.execute("SELECT * FROM liabilities WHERE user_id=? ORDER BY id", (uid,))]
    upd = defaultdict(list)
    for r in con.execute("SELECT u.* FROM liability_updates u JOIN liabilities l ON l.id=u.liability_id "
                         "WHERE l.user_id=? ORDER BY u.date, u.id", (uid,)):
        upd[r["liability_id"]].append(dict(r))
    out = []
    for l in rows:
        u = upd[l["id"]]
        outstanding = u[-1]["outstanding"] if u else l["principal"]
        end_date = months_left = None
        if l.get("start_date") and l.get("tenure_months"):
            sd = _d(l["start_date"])
            m = sd.month - 1 + int(l["tenure_months"])
            y, mo = sd.year + m // 12, m % 12 + 1
            end = date(y, mo, min(sd.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]))
            end_date = end.isoformat()
            t = date.today()
            months_left = max(0, (end.year - t.year) * 12 + end.month - t.month - (1 if end.day < t.day else 0))
        out.append({
            **l,
            "end_date": end_date,
            "months_left": months_left,
            "type_label": LIABILITY_TYPE_MAP.get(l["type"], l["type"]),
            "outstanding": round(outstanding, 2),
            "outstanding_date": u[-1]["date"] if u else l["start_date"],
            "repaid_pct": round((1 - outstanding / l["principal"]) * 100, 1) if l["principal"] else None,
        })
    return out


def get_settings(con, uid):
    s = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings WHERE user_id=?", (uid,))}
    def num(k, default=None):
        try:
            return float(s[k]) if s.get(k) not in (None, "") else default
        except ValueError:
            return default
    return {
        "name": s.get("name") or "",
        "age": num("age"),
        "risk_profile": s.get("risk_profile") or "moderate",
        "monthly_expenses": num("monthly_expenses"),
        "annual_income": num("annual_income"),
        "dependents": num("dependents"),
        "tax_regime": s.get("tax_regime") or "new",
    }


def allocation(assets):
    by_cat = defaultdict(float)
    by_type = defaultdict(float)
    for a in assets:
        for cat, w in a["weights"].items():
            by_cat[cat] += a["current_value"] * w
        by_type[a["type_label"]] += a["current_value"]
    total = sum(by_cat.values())
    cats = []
    for c in CATEGORIES:
        v = by_cat.get(c["key"], 0.0)
        cats.append({**c, "value": round(v, 2), "pct": round(v / total * 100, 2) if total else 0})
    types = sorted(
        ({"label": k, "value": round(v, 2), "pct": round(v / total * 100, 2) if total else 0} for k, v in by_type.items()),
        key=lambda x: -x["value"],
    )
    return cats, types


def by_group(assets):
    """Totals per asset group (Real Estate, Mutual Funds, Stocks, ...), in catalog order."""
    total = sum(a["current_value"] for a in assets)
    groups = {}
    for a in assets:
        g = groups.setdefault(a["group"], {"group": a["group"], "count": 0, "invested": 0.0, "value": 0.0, "types": defaultdict(float)})
        g["count"] += 1
        g["invested"] += a["invested"]
        g["value"] += a["current_value"]
        g["types"][a["type_label"]] += a["current_value"]
    out = []
    for name in GROUP_ORDER + sorted(set(groups) - set(GROUP_ORDER)):
        if name not in groups:
            continue
        g = groups[name]
        out.append({
            "group": name, "count": g["count"],
            "invested": round(g["invested"], 2), "value": round(g["value"], 2),
            "gain": round(g["value"] - g["invested"], 2),
            "gain_pct": round((g["value"] - g["invested"]) / g["invested"] * 100, 2) if g["invested"] > 0 else None,
            "pct": round(g["value"] / total * 100, 2) if total else 0,
            "types": sorted(({"label": k, "value": round(v, 2)} for k, v in g["types"].items()), key=lambda x: -x["value"]),
        })
    return out


def summary(con, uid):
    assets = load_assets(con, uid)
    liabs = load_liabilities(con, uid)
    total_assets = sum(a["current_value"] for a in assets)
    invested = sum(a["invested"] for a in assets)
    total_liabs = sum(l["outstanding"] for l in liabs)
    cats, types = allocation(assets)
    history = [dict(r) for r in con.execute(
        "SELECT date, assets, liabilities FROM snapshots WHERE user_id=? ORDER BY date", (uid,))]
    for h in history:
        h["net_worth"] = round(h["assets"] - h["liabilities"], 2)
    return {
        "total_assets": round(total_assets, 2),
        "total_invested": round(invested, 2),
        "total_gain": round(total_assets - invested, 2),
        "total_liabilities": round(total_liabs, 2),
        "net_worth": round(total_assets - total_liabs, 2),
        "monthly_emi": round(sum(l["emi"] or 0 for l in liabs if l["outstanding"] > 0), 2),
        "asset_count": len(assets),
        "liability_count": len(liabs),
        "by_category": cats,
        "by_type": types,
        "by_group": by_group(assets),
        "history": history,
    }


def record_snapshot(con, uid):
    assets = load_assets(con, uid)
    liabs = load_liabilities(con, uid)
    con.execute(
        "INSERT INTO snapshots(user_id, date, assets, liabilities) VALUES (?,?,?,?) "
        "ON CONFLICT(user_id, date) DO UPDATE SET assets=excluded.assets, liabilities=excluded.liabilities",
        (uid, today(), sum(a["current_value"] for a in assets), sum(l["outstanding"] for l in liabs)),
    )


# ---------- growth series: invested vs current value over time ----------

def _value_at(txs, vals, d):
    """Value of one asset on date d: latest valuation <= d, plus net transactions after it."""
    v = None
    for x in vals:  # sorted by date, id
        if x["date"] <= d:
            v = x
    if v is None:
        return sum((x["amount"] if x["kind"] == "BUY" else -x["amount"]) for x in txs if x["date"] <= d)
    later = sum((x["amount"] if x["kind"] == "BUY" else -x["amount"])
                for x in txs if v["date"] < x["date"] <= d)
    return v["value"] + later


def _invested_at(txs, d):
    return sum((x["amount"] if x["kind"] == "BUY" else -x["amount"]) for x in txs if x["date"] <= d)


def growth_series(con, uid, asset_id=None):
    """One point per date on which a purchase/sale or value update was recorded."""
    where, args = ("WHERE a.user_id=? AND a.id=?", (uid, asset_id)) if asset_id else ("WHERE a.user_id=?", (uid,))
    txs, vals = defaultdict(list), defaultdict(list)
    for r in con.execute(f"SELECT x.* FROM transactions x JOIN assets a ON a.id=x.asset_id {where} "
                         "ORDER BY x.date, x.id", args):
        txs[r["asset_id"]].append(dict(r))
    for r in con.execute(f"SELECT x.* FROM valuations x JOIN assets a ON a.id=x.asset_id {where} "
                         "ORDER BY x.date, x.id", args):
        vals[r["asset_id"]].append(dict(r))
    ids = set(txs) | set(vals)
    val_dates = {x["date"] for v in vals.values() for x in v}
    dates = sorted({x["date"] for t in txs.values() for x in t} | val_dates | ({today()} if ids else set()))

    points = []
    for d in dates:
        invested = sum(_invested_at(txs[i], d) for i in ids)
        value = sum(max(0.0, _value_at(txs[i], vals[i], d)) for i in ids)
        gain = value - invested
        points.append({
            "date": d,
            "invested": round(invested, 2),
            "value": round(value, 2),
            "gain": round(gain, 2),
            "gain_pct": round(gain / invested * 100, 2) if invested > 0 else None,
            "value_update": d in val_dates,
        })
    return points
