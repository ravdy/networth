"""Fictional sample portfolio used by the demo instance (NETWORTH_DEMO=1).

seed_user(con, uid) fills one account with ~10 years of made-up history: purchases, quarterly value
updates with market swings, amortising loans and month-end net worth snapshots. Nothing here is real.
"""
import random
from collections import defaultdict
from datetime import date, timedelta

from .portfolio import record_snapshot

TODAY = date.today()


def d(y, m, day=1):
    return date(y, m, min(day, 28)).isoformat()


def monthly(start, months, amount, day=5):
    y, m = start
    out = []
    for _ in range(months):
        dt = date(y, m, day)
        if dt > TODAY:
            break
        out.append((dt.isoformat(), "BUY", amount))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def yearly(first_year, month, day, amount):
    return [(date(y, month, day).isoformat(), "BUY", amount)
            for y in range(first_year, TODAY.year + 1) if date(y, month, day) <= TODAY]


# name, type, notes, transactions [(date, kind, amount)], valuations [(date, value)]
ASSETS = [
    ("2BHK Flat - Whitefield", "re_residential", "Self-occupied",
     [(d(2019, 3, 15), "BUY", 6500000)], [(d(2023, 1, 10), 8200000), (d(2025, 6, 1), 9400000), (d(2026, 10, 1), 9800000)]),
    ("Plot - Mysuru Road", "re_land", "Investment plot",
     [(d(2021, 8, 20), "BUY", 2400000)], [(d(2024, 4, 1), 3100000), (d(2026, 9, 1), 3600000)]),
    ("Embassy REIT", "reit", "",
     [(d(2023, 2, 10), "BUY", 150000), (d(2024, 7, 12), "BUY", 100000)], [(d(2026, 11, 1), 292000)]),

    ("Parag Parikh Flexi Cap - SIP", "mf_equity", "₹15k monthly SIP",
     monthly((2022, 1), 60, 15000), [(d(2024, 3, 31), 520000), (d(2025, 3, 31), 790000), (d(2026, 11, 1), 1185000)]),
    ("Nifty 50 Index Fund - SIP", "mf_index", "₹10k monthly SIP",
     monthly((2023, 4), 60, 10000), [(d(2025, 3, 31), 265000), (d(2026, 11, 1), 489000)]),
    ("Mirae Asset ELSS", "mf_elss", "80C (old regime years)",
     yearly(2021, 3, 20, 50000)[:4], [(d(2026, 11, 1), 318000)]),
    ("ICICI Balanced Advantage", "mf_hybrid", "",
     [(d(2022, 6, 1), "BUY", 200000), (d(2024, 9, 1), "BUY", 100000)], [(d(2026, 11, 1), 402000)]),
    ("HDFC Short Duration Debt", "mf_debt", "",
     [(d(2023, 11, 1), "BUY", 300000)], [(d(2026, 11, 1), 361000)]),
    ("Nippon Silver ETF FoF", "mf_commodity", "",
     [(d(2024, 2, 1), "BUY", 80000)], [(d(2026, 11, 1), 131000)]),

    ("Zerodha - Indian stocks", "stock_in", "Large-cap basket",
     [(d(2020, 5, 4), "BUY", 300000), (d(2022, 2, 14), "BUY", 200000), (d(2024, 6, 20), "SELL", 120000)],
     [(d(2023, 3, 31), 610000), (d(2025, 3, 31), 720000), (d(2026, 11, 1), 795000)]),
    ("US stocks (Vested)", "stock_us", "",
     [(d(2022, 9, 1), "BUY", 150000), (d(2024, 1, 15), "BUY", 100000)], [(d(2026, 11, 1), 336000)]),
    ("Company RSUs", "esop", "Vested units",
     [(d(2024, 4, 1), "BUY", 220000), (d(2025, 4, 1), "BUY", 240000)], [(d(2026, 11, 1), 585000)]),

    ("Gold jewellery", "gold_physical", "Approx. 120 g",
     [(d(2015, 11, 10), "BUY", 330000)], [(d(2022, 1, 1), 580000), (d(2026, 11, 1), 1490000)]),
    ("SGB 2021 Series IX", "gold_sgb", "",
     [(d(2021, 12, 30), "BUY", 97000)], [(d(2026, 11, 1), 248000)]),
    ("Jeweller gold scheme", "gold_scheme", "₹5k x 11 months",
     monthly((2026, 1), 11, 5000, day=10), []),

    ("Old FD (matured, used for flat down payment)", "fd", "Closed 2019",
     [(d(2016, 6, 1), "BUY", 400000), (d(2017, 6, 1), "BUY", 300000), (d(2019, 3, 1), "SELL", 700000)], []),
    ("SBI Fixed Deposit", "fd", "7.1% p.a., 2 yrs",
     [(d(2025, 8, 1), "BUY", 500000)], [(d(2026, 11, 1), 542000)]),
    ("PPF", "ppf", "",
     yearly(2018, 4, 5, 150000), [(d(2026, 4, 1), 1810000)]),
    ("EPF", "epf", "Employer + employee",
     monthly((2016, 1), 140, 12500, day=15), [(d(2026, 3, 31), 2210000)]),
    ("NPS Tier I", "nps", "80CCD(1B)",
     yearly(2022, 1, 15, 50000), [(d(2026, 11, 1), 312000)]),

    ("HDFC Savings", "savings", "Salary account",
     [(d(2016, 1, 5), "BUY", 60000), (d(2019, 1, 5), "BUY", 80000), (d(2023, 1, 5), "BUY", 140000)], []),
    ("Emergency fund - Liquid Fund", "mf_liquid", "6 months expenses",
     [(d(2024, 1, 5), "BUY", 400000), (d(2025, 1, 5), "BUY", 100000)], [(d(2026, 11, 1), 568000)]),
    ("Cash at home", "cash", "", [(d(2020, 4, 1), "BUY", 25000)], []),

    ("Bitcoin (CoinDCX)", "crypto", "", [(d(2021, 3, 1), "BUY", 60000), (d(2023, 7, 1), "BUY", 40000)],
     [(d(2022, 12, 31), 45000), (d(2026, 11, 1), 215000)]),

    ("LIC Jeevan Anand", "ulip", "Annual premium ₹36k", yearly(2017, 6, 20, 36000), [(d(2026, 6, 20), 310000)]),
    ("HDFC Life Click2Wealth (ULIP)", "ulip", "Annual premium ₹60k", yearly(2022, 2, 10, 60000), [(d(2026, 11, 1), 335000)]),

    ("Loan to cousin", "lent", "To be returned by Mar 2027", [(d(2026, 2, 1), "BUY", 150000)], []),
    ("Rental deposit - flat", "rental_deposit", "", [(d(2024, 6, 1), "BUY", 120000)], []),
    ("Car - Hyundai Creta", "vehicle", "Depreciating asset",
     [(d(2023, 10, 5), "BUY", 1450000)], [(d(2024, 10, 1), 1150000), (d(2026, 10, 1), 920000)]),
]

# name, type, principal, rate, emi, start, tenure_months, notes, updates [(date, outstanding)]
LIABILITIES = [
    ("Home loan - SBI", "home_loan", 5000000, 8.5, 43391, d(2019, 4, 5), 240, "Whitefield flat",
     [(d(2022, 4, 1), 4450000), (d(2024, 4, 1), 4010000), (d(2026, 11, 1), 3440000)]),
    ("Car loan - HDFC", "car_loan", 1000000, 9.2, 20855, d(2023, 10, 5), 60, "",
     [(d(2025, 1, 1), 720000), (d(2026, 11, 1), 395000)]),
    ("Personal loan", "personal_loan", 300000, 13.5, 10180, d(2025, 6, 1), 36, "For plot registration",
     [(d(2026, 11, 1), 182000)]),
    ("Credit card - Amex", "credit_card", 45000, 42, None, d(2026, 10, 25), None, "Current statement",
     []),
]

SETTINGS = {"name": "Demo User", "age": "38", "risk_profile": "moderate", "monthly_expenses": "85000",
            "annual_income": "2400000", "dependents": "2", "tax_regime": "new"}


# ---------- history generation ----------
MARKET = {"mf_equity", "mf_index", "mf_elss", "mf_hybrid", "mf_intl", "stock_in", "stock_us", "esop", "nps", "crypto", "reit"}
# rough market mood by date (multiplier on the smooth trend) -> COVID crash, 2022 correction
MOOD = [("2020-02-29", 1.0), ("2020-03-31", 0.70), ("2020-06-30", 0.86), ("2020-12-31", 1.0),
        ("2022-03-31", 1.0), ("2022-06-30", 0.90), ("2022-12-31", 1.0), ("2024-09-30", 1.04), ("2025-03-31", 0.95), ("2025-09-30", 1.0)]


def _interp(points, x):
    """Linear interpolation over [(iso_date, y)] sorted by date; flat outside."""
    if x <= points[0][0]:
        return points[0][1]
    for (d0, y0), (d1, y1) in zip(points, points[1:]):
        if d0 <= x <= d1:
            t0, t1, tx = (date.fromisoformat(v).toordinal() for v in (d0, d1, x))
            return y0 + (y1 - y0) * (tx - t0) / ((t1 - t0) or 1)
    return points[-1][1]


def invested_at(txs, dt):
    return sum(a if k == "BUY" else -a for x, k, a in txs if x <= dt)


def quarter_ends(start, end):
    out = []
    for y in range(int(start[:4]), int(end[:4]) + 1):
        for md in ("03-31", "06-30", "09-30", "12-31"):
            q = f"{y}-{md}"
            if start < q < end:
                out.append(q)
    return out


def build_valuations(typ, txs, given, rnd):
    """Add a value update every quarter between first purchase and the last real value,
    following a smooth growth path (value/invested ratio) with market swings."""
    if not given:
        return []
    first = min(x for x, *_ in txs)
    anchors = [(first, 1.0)] + [(vd, v / invested_at(txs, vd)) for vd, v in given if invested_at(txs, vd) > 0]
    have = [vd for vd, _ in given]
    vals = list(given)
    for q in quarter_ends(first, given[-1][0]):
        if any(abs(date.fromisoformat(q).toordinal() - date.fromisoformat(h).toordinal()) < 45 for h in have):
            continue
        inv = invested_at(txs, q)
        if inv <= 0:
            continue
        ratio = _interp(anchors, q)
        if typ in MARKET:
            ratio *= _interp(MOOD, q) * rnd.uniform(0.97, 1.03)
        vals.append((q, round(inv * ratio, -2)))
    return sorted(vals)


def value_at(txs, vals, dt):
    """Same rule as the app (latest value + later purchases/sales), but interpolated between
    value updates so month-end history is smooth."""
    inv = invested_at(txs, dt)
    if not vals or dt < vals[0][0]:
        first = min(x for x, *_ in txs)
        if not vals or dt < first:
            return max(inv, 0)
        r = _interp([(first, 1.0), (vals[0][0], vals[0][1] / max(invested_at(txs, vals[0][0]), 1))], dt)
        return max(inv * r, 0)
    if dt >= vals[-1][0]:
        vd, v = vals[-1]
        return v + inv - invested_at(txs, vd)
    pts = [(vd, v / max(invested_at(txs, vd), 1)) for vd, v in vals]
    return max(inv * _interp(pts, dt), 0)


def months_between(a, b):
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    return (b.year - a.year) * 12 + b.month - a.month


def outstanding(p, rate, n, start, dt):
    if dt < start:
        return 0.0
    if not n or not rate:
        return p
    k = min(max(months_between(start, dt), 0), n)
    r = rate / 1200
    return max(p * ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1), 0)


def month_ends(start, end):
    out, y, m = [], int(start[:4]), int(start[5:7])
    while True:
        e = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()
        if e >= end:
            return out
        out.append(e)
        y, m = y + (m == 12), m % 12 + 1


def seed_user(con, uid):
    """Give one (empty) account its own copy of the sample portfolio."""
    rnd = random.Random(42)
    today = TODAY.isoformat()
    series = []
    for name, typ, notes, txs, given in ASSETS:
        aid = con.execute("INSERT INTO assets(name, type, notes, user_id) VALUES (?,?,?,?)",
                          (name, typ, notes, uid)).lastrowid
        vals = build_valuations(typ, txs, sorted(given), rnd)
        con.executemany("INSERT INTO transactions(asset_id, date, kind, amount) VALUES (?,?,?,?)",
                        [(aid, dt, kind, amt) for dt, kind, amt in txs])
        con.executemany("INSERT INTO valuations(asset_id, date, value) VALUES (?,?,?)",
                        [(aid, dt, v) for dt, v in vals])
        series.append((txs, vals))

    loans = []
    for name, typ, p, r, emi, start, ten, notes, _ in LIABILITIES:
        if ten and r:
            rr = r / 1200
            emi = round(p * rr * (1 + rr) ** ten / ((1 + rr) ** ten - 1))
        lid = con.execute(
            "INSERT INTO liabilities(name, type, principal, interest_rate, emi, start_date, tenure_months, notes, user_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)", (name, typ, p, r, emi, start, ten, notes, uid)).lastrowid
        if ten:  # balance update every quarter, plus this month
            con.executemany("INSERT INTO liability_updates(liability_id, date, outstanding) VALUES (?,?,?)",
                            [(lid, q, round(outstanding(p, r, ten, start, q), -2))
                             for q in quarter_ends(start, today) + [TODAY.replace(day=1).isoformat()]])
        loans.append((typ, p, r, ten, start))

    con.executemany("INSERT INTO settings(user_id, key, value) VALUES (?,?,?) "
                    "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value",
                    [(uid, k, v) for k, v in SETTINGS.items()])

    # month-end net worth history from the first investment to today
    first = min(x for txs, _ in series for x, *_ in txs)
    rows = []
    for dt in month_ends(first, today):
        a = sum(value_at(txs, vals, dt) for txs, vals in series)
        li = sum(outstanding(p, r, ten, start, dt) for typ, p, r, ten, start in loans if typ != "credit_card")
        rows.append((uid, dt, round(a), round(li)))
    con.executemany("INSERT INTO snapshots(user_id, date, assets, liabilities) VALUES (?,?,?,?)", rows)
    record_snapshot(con, uid)
