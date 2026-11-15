"""Rule-based allocation guidance for Indian investors.

These are widely used thumb-rules (age-based equity, emergency fund, gold 5–15%,
crypto as a small satellite, etc.). They are educational, not personalised advice.
"""
from .catalog import CATEGORY_LABELS

FINANCIAL_CATS = ["equity", "debt", "gold", "cash", "crypto"]

PROFILE = {
    #                equity adj, gold, crypto, cash
    "conservative": (-15, 12, 0, 7),
    "moderate":     (0,   10, 2, 5),
    "aggressive":   (10,  8,  5, 5),
}

TOLERANCE = {"equity": 5, "debt": 5, "gold": 3, "cash": 3, "crypto": 1}

INDIA_NOTES = [
    ("Equity tax", "Listed equity & equity MFs: LTCG (held > 12 months) taxed at 12.5% above ₹1.25 lakh/year; STCG at 20%."),
    ("Debt MF tax", "Debt funds bought on/after 1 Apr 2023 are taxed at your slab rate regardless of holding period — FDs and debt funds are now tax-similar."),
    ("PPF / EPF", "PPF is EEE (tax-free) with a 15-year lock-in and ₹1.5 lakh/year cap. EPF/VPF interest is tax-free up to ₹2.5 lakh/year of employee contribution."),
    ("Gold", "Prefer Gold ETFs / Gold MFs over jewellery for investment — no making charges or purity risk. New SGB tranches have been paused; existing SGBs trade on NSE/BSE and are tax-free if held to maturity."),
    ("Real estate", "Property LTCG (held > 24 months) is 12.5% without indexation; for property bought before 23 Jul 2024, individuals may choose 20% with indexation. Factor in stamp duty, maintenance and illiquidity."),
    ("Crypto", "Crypto (VDA) gains are taxed at a flat 30% + 1% TDS on transfers; losses cannot be set off against any other income. Keep it a small satellite."),
    ("Tax regime", "Under the new regime (default), most deductions — 80C, 80D, home-loan interest on self-occupied property — are not available. Employer NPS contribution under 80CCD(2) is still allowed."),
]


def _fmt(v):
    """Indian-style rupee formatting (lakh / crore)."""
    v = float(v)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e7:
        return f"{sign}₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"{sign}₹{v / 1e5:.2f} L"
    return f"{sign}₹{v:,.0f}"


def target_allocation(age, risk):
    age = age or 35
    eq_adj, gold, crypto, cash = PROFILE.get(risk, PROFILE["moderate"])
    equity = 100 - age + eq_adj
    equity = max(10, min(equity, 100 - gold - crypto - cash - 10))
    debt = 100 - equity - gold - crypto - cash
    return {"equity": equity, "debt": debt, "gold": gold, "cash": cash, "crypto": crypto}


def build(settings, assets, liabilities, summary):
    items = []

    def add(severity, area, title, detail):
        items.append({"severity": severity, "area": area, "title": title, "detail": detail})

    age = settings.get("age")
    risk = settings.get("risk_profile") or "moderate"
    expenses = settings.get("monthly_expenses")
    income = settings.get("annual_income")
    dependents = settings.get("dependents") or 0

    if not age or not expenses or not income:
        add("info", "Profile", "Complete your profile for sharper guidance",
            "Set your age, monthly expenses and annual income in Settings. Until then, recommendations assume age 35 and skip emergency-fund / EMI checks.")

    cat_value = {c["key"]: c["value"] for c in summary["by_category"]}
    total_assets = summary["total_assets"]
    fin_total = sum(cat_value.get(k, 0) for k in FINANCIAL_CATS)

    targets = target_allocation(age, risk)
    target_rows = []
    for k in FINANCIAL_CATS:
        cur = cat_value.get(k, 0)
        cur_pct = cur / fin_total * 100 if fin_total else 0
        tgt_val = targets[k] / 100 * fin_total
        target_rows.append({
            "key": k, "label": CATEGORY_LABELS[k],
            "current_value": round(cur, 2), "current_pct": round(cur_pct, 2),
            "target_pct": targets[k], "target_value": round(tgt_val, 2),
            "diff_value": round(tgt_val - cur, 2), "tolerance": TOLERANCE[k],
        })

    if total_assets <= 0:
        add("info", "Getting started", "Add your first asset",
            "Go to Assets → Add asset. Record each purchase, then update the market value whenever you check it.")
        return _result(items, target_rows, targets, age, risk, None, fin_total)

    # ---- Allocation drift (financial assets only) ----
    if fin_total > 0:
        in_band = True
        for r in target_rows:
            drift = r["current_pct"] - r["target_pct"]
            if abs(drift) <= r["tolerance"]:
                continue
            in_band = False
            label = r["label"]
            if drift > 0:
                if r["key"] == "crypto":
                    add("high", "Allocation", f"Crypto is {r['current_pct']:.1f}% of financial assets",
                        f"Suggested ceiling for a {risk} profile is {r['target_pct']}%. Consider trimming ~{_fmt(-r['diff_value'])}. "
                        "Crypto is unregulated in India, taxed at 30% + 1% TDS, and losses can't be set off.")
                else:
                    add("medium", "Allocation", f"{label} is overweight ({r['current_pct']:.1f}% vs {r['target_pct']}% target)",
                        f"About {_fmt(-r['diff_value'])} above target. Rebalance by pausing fresh money into {label.lower()} "
                        "and redirecting SIPs, rather than selling (avoids capital-gains tax).")
            else:
                hint = {
                    "equity": "Diversified index funds (Nifty 50 / Nifty Next 50) or flexi-cap funds via monthly SIP.",
                    "debt": "PPF/EPF/VPF first (tax-free), then short-duration debt funds, FDs or RBI Floating Rate Bonds.",
                    "gold": "Gold ETFs or Gold Mutual Funds (SIP-able, no making charges).",
                    "cash": "Liquid fund or sweep-in FD for your emergency fund.",
                    "crypto": "",
                }[r["key"]]
                if r["key"] != "crypto":
                    add("medium", "Allocation", f"{label} is underweight ({r['current_pct']:.1f}% vs {r['target_pct']}% target)",
                        f"Add about {_fmt(r['diff_value'])} over time. {hint}")
        if in_band:
            add("good", "Allocation", "Financial asset allocation is within target bands",
                f"Equity / debt / gold / cash are all within tolerance of the {risk} target for age {int(age or 35)}.")

    # ---- Real estate concentration ----
    re_pct = cat_value.get("real_estate", 0) / total_assets * 100
    if re_pct > 60:
        add("high", "Real estate", f"Real estate is {re_pct:.0f}% of total assets",
            "Very concentrated and illiquid. Typical guidance is ≤ 30–40% of net worth beyond your own home. "
            "Avoid buying more property; direct new savings to financial assets. REITs give property exposure with liquidity.")
    elif re_pct > 40:
        add("medium", "Real estate", f"Real estate is {re_pct:.0f}% of total assets",
            "Above the commonly suggested 30–40% range. Favour financial assets for new investments so you can meet goals without selling property.")
    elif re_pct > 0:
        add("good", "Real estate", f"Real estate at {re_pct:.0f}% of total assets is reasonable",
            "Keep property within ~30–40% of net worth for liquidity.")

    # ---- Emergency fund ----
    if expenses:
        months_needed = 9 if dependents >= 2 or risk == "conservative" else 6
        liquid = cat_value.get("cash", 0) + sum(a["current_value"] for a in assets if a["type"] == "fd")
        months = liquid / expenses
        need = months_needed * expenses
        if months < 3:
            add("high", "Emergency fund", f"Emergency fund covers only {months:.1f} months",
                f"Target {months_needed} months ({_fmt(need)}). Build it before new risky investments — keep it in savings, sweep-in FD or a liquid fund.")
        elif months < months_needed:
            add("medium", "Emergency fund", f"Emergency fund covers {months:.1f} months",
                f"Top it up by {_fmt(need - liquid)} to reach {months_needed} months of expenses.")
        else:
            add("good", "Emergency fund", f"Emergency fund covers {months:.1f} months of expenses",
                "Cash, liquid funds and FDs together meet the 6–9 month guideline.")

    # ---- Gold form ----
    gold_total = cat_value.get("gold", 0)
    phys = sum(a["current_value"] for a in assets if a["type"] == "gold_physical")
    if gold_total > 0 and phys / gold_total > 0.6:
        add("info", "Gold", "Most of your gold is physical",
            "Jewellery isn't an efficient investment (making charges, purity, storage). For future gold allocation, prefer Gold ETFs / Gold MFs.")

    # ---- Single-stock concentration ----
    if fin_total > 0:
        for a in assets:
            if a["type"] in ("stock_in", "stock_us", "esop", "unlisted") and a["current_value"] / fin_total > 0.10:
                add("medium", "Concentration", f"'{a['name']}' is {a['current_value'] / fin_total * 100:.0f}% of financial assets",
                    "A single stock above ~10% adds company-specific risk. Consider gradually diversifying (especially ESOPs/RSUs of your employer).")

    # ---- International diversification ----
    eq = cat_value.get("equity", 0)
    intl = sum(a["current_value"] for a in assets if a["type"] in ("stock_us", "mf_intl"))
    if eq > 0 and intl == 0 and risk != "conservative":
        add("info", "Diversification", "No international equity exposure",
            "Many planners suggest 10–15% of equity in global funds (e.g. US index FoFs) to diversify currency and country risk.")

    # ---- Liabilities ----
    total_debt = sum(l["outstanding"] for l in liabilities)
    for l in liabilities:
        if l["outstanding"] <= 0:
            continue
        rate = l.get("interest_rate") or 0
        if l["type"] == "credit_card":
            add("high", "Debt", f"Clear credit-card dues: {l['name']} ({_fmt(l['outstanding'])})",
                "Revolving card balances cost ~36–45% p.a. Pay this off before any investment.")
        elif rate >= 12 or l["type"] in ("personal_loan", "bnpl"):
            add("high", "Debt", f"Prepay high-interest loan: {l['name']} ({rate or '?'}% p.a.)",
                "No investment reliably beats a 12%+ loan after tax. Use surplus / part of FDs to prepay.")
        elif l["type"] == "home_loan" and rate >= 9:
            add("info", "Debt", f"Home loan at {rate}% — consider part-prepayment or a rate-reset",
                "Ask your bank to move you to the current repo-linked rate, or refinance. Prepaying early in the tenure saves the most interest.")
    if total_assets > 0 and total_debt > 0:
        dta = total_debt / total_assets * 100
        if dta > 50:
            add("high", "Debt", f"Debt is {dta:.0f}% of your assets",
                "Leverage is high. Prioritise reducing liabilities before increasing risk exposure.")
        elif dta <= 30:
            add("good", "Debt", f"Debt-to-asset ratio is healthy ({dta:.0f}%)", "Comfortably below the 30–40% comfort zone.")
    if income and summary["monthly_emi"] > 0:
        ratio = summary["monthly_emi"] / (income / 12) * 100
        if ratio > 40:
            add("high", "Debt", f"EMIs take {ratio:.0f}% of monthly income",
                "Keep total EMIs under ~30–40% of take-home income. Avoid new loans and prepay the costliest one first.")
        elif ratio > 30:
            add("medium", "Debt", f"EMIs take {ratio:.0f}% of monthly income", "Close to the 40% ceiling — be careful taking on new loans.")

    # ---- Tax-advantaged & retirement ----
    types = {a["type"] for a in assets}
    if not types & {"ppf", "epf", "nps"}:
        add("info", "Retirement", "No PPF / EPF / NPS found",
            "These form the stable, tax-efficient core of an Indian retirement corpus. PPF is tax-free; NPS adds extra deductions (80CCD(1B) in old regime, employer 80CCD(2) in both regimes).")
    if settings.get("tax_regime") == "old" and not types & {"ppf", "epf", "mf_elss", "ssy", "ulip"}:
        add("info", "Tax", "Use your ₹1.5 lakh Section 80C limit",
            "On the old regime: ELSS (3-yr lock-in, equity), PPF or VPF can fill 80C.")

    # ---- Protection ----
    if income:
        add("info", "Protection", "Check your insurance cover",
            f"Term life cover of 10–15× annual income (≈ {_fmt(income * 10)}–{_fmt(income * 15)}) if anyone depends on you, "
            "and a health cover of at least ₹10 lakh for the family (plus a super top-up). Insurance isn't tracked here as an asset.")

    return _result(items, target_rows, targets, age, risk, re_pct, fin_total)


def _result(items, target_rows, targets, age, risk, re_pct, fin_total):
    order = {"high": 0, "medium": 1, "info": 2, "good": 3}
    items.sort(key=lambda x: order[x["severity"]])
    return {
        "profile": {"age": age, "assumed_age": age or 35, "risk_profile": risk},
        "targets": target_rows,
        "financial_total": round(fin_total, 2),
        "real_estate_pct": round(re_pct, 2) if re_pct is not None else None,
        "items": items,
        "notes": [{"title": t, "detail": d} for t, d in INDIA_NOTES],
        "disclaimer": "Rule-of-thumb guidance for education only — not investment, tax or legal advice. "
                      "Tax rules reflect FY 2025-26 and change with each Budget; verify with a SEBI-registered adviser / CA.",
    }
