"""Asset / liability type catalog, tuned for Indian investors.

Each asset type maps to one or more allocation categories with weights
(e.g. a hybrid fund is ~65% equity / 35% debt).
"""

CATEGORIES = [
    {"key": "equity", "label": "Equity"},
    {"key": "debt", "label": "Debt & Fixed Income"},
    {"key": "real_estate", "label": "Real Estate"},
    {"key": "gold", "label": "Gold & Silver"},
    {"key": "cash", "label": "Cash & Liquid"},
    {"key": "crypto", "label": "Crypto"},
    {"key": "other", "label": "Other"},
]

ASSET_TYPES = [
    # group, key, label, category weights
    ("Real Estate", "re_residential", "Residential Property (Flat / House)", {"real_estate": 1}),
    ("Real Estate", "re_commercial", "Commercial Property", {"real_estate": 1}),
    ("Real Estate", "re_land", "Land / Plot", {"real_estate": 1}),
    ("Real Estate", "reit", "REITs / InvITs", {"real_estate": 1}),

    ("Mutual Funds", "mf_equity", "Mutual Fund – Equity (Large/Mid/Small/Flexi)", {"equity": 1}),
    ("Mutual Funds", "mf_elss", "Mutual Fund – ELSS (Tax Saver)", {"equity": 1}),
    ("Mutual Funds", "mf_index", "Index Fund / Equity ETF", {"equity": 1}),
    ("Mutual Funds", "mf_intl", "International Fund / FoF", {"equity": 1}),
    ("Mutual Funds", "mf_hybrid", "Mutual Fund – Hybrid / Balanced Advantage", {"equity": 0.65, "debt": 0.35}),
    ("Mutual Funds", "mf_debt", "Mutual Fund – Debt", {"debt": 1}),
    ("Mutual Funds", "mf_commodity", "Mutual Fund – Gold / Silver (ETF FoF)", {"gold": 1}),
    ("Mutual Funds", "mf_liquid", "Liquid / Overnight Fund", {"cash": 1}),

    ("Stocks", "stock_in", "Stocks – Indian (NSE/BSE)", {"equity": 1}),
    ("Stocks", "stock_us", "Stocks – US / International", {"equity": 1}),
    ("Stocks", "esop", "ESOPs / RSUs", {"equity": 1}),
    ("Stocks", "pms_aif", "PMS / AIF", {"equity": 1}),
    ("Stocks", "unlisted", "Unlisted / Pre-IPO Shares", {"equity": 1}),

    ("Gold & Silver", "gold_physical", "Gold – Physical (Jewellery / Coins / Bars)", {"gold": 1}),
    ("Gold & Silver", "gold_sgb", "Sovereign Gold Bonds (SGB)", {"gold": 1}),
    ("Gold & Silver", "gold_etf", "Gold ETF / Gold Mutual Fund", {"gold": 1}),
    ("Gold & Silver", "gold_digital", "Digital Gold", {"gold": 1}),
    ("Gold & Silver", "gold_scheme", "Gold Savings Scheme / Gold EMI (jeweller)", {"gold": 1}),
    ("Gold & Silver", "silver", "Silver (Physical / ETF)", {"gold": 1}),

    ("Fixed Income", "fd", "Fixed Deposit (Bank / Corporate)", {"debt": 1}),
    ("Fixed Income", "rd", "Recurring Deposit", {"debt": 1}),
    ("Fixed Income", "ppf", "PPF", {"debt": 1}),
    ("Fixed Income", "epf", "EPF / VPF", {"debt": 1}),
    ("Fixed Income", "nps", "NPS (Tier I / II)", {"equity": 0.5, "debt": 0.5}),
    ("Fixed Income", "post_office", "Post Office (NSC / KVP / SCSS / MIS)", {"debt": 1}),
    ("Fixed Income", "ssy", "Sukanya Samriddhi Yojana", {"debt": 1}),
    ("Fixed Income", "bonds", "Bonds / NCDs / Debentures", {"debt": 1}),
    ("Fixed Income", "gsec", "G-Secs / T-Bills / RBI Bonds", {"debt": 1}),

    ("Cash", "savings", "Savings Account", {"cash": 1}),
    ("Cash", "cash", "Cash in Hand", {"cash": 1}),

    ("Crypto", "crypto", "Crypto (BTC / ETH / others)", {"crypto": 1}),

    ("Insurance", "ulip", "Insurance – ULIP / Endowment / LIC policy (premiums paid / surrender value)", {"debt": 1}),

    ("Other", "p2p", "P2P Lending", {"debt": 1}),
    ("Other", "lent", "Money Lent (to friends / family)", {"other": 1}),
    ("Other", "rental_deposit", "Rental / Security Deposit", {"other": 1}),
    ("Other", "business", "Business / Startup Stake", {"other": 1}),
    ("Other", "vehicle", "Vehicle", {"other": 1}),
    ("Other", "other", "Other Asset", {"other": 1}),
]

LIABILITY_TYPES = [
    ("home_loan", "Home Loan"),
    ("lap", "Loan Against Property"),
    ("property_dues", "Property Balance Due (builder)"),
    ("car_loan", "Car / Two-wheeler Loan"),
    ("personal_loan", "Personal Loan"),
    ("education_loan", "Education Loan"),
    ("gold_loan", "Gold Loan"),
    ("credit_card", "Credit Card Outstanding"),
    ("bnpl", "Consumer Durable / BNPL"),
    ("las", "Loan Against Securities / FD"),
    ("family", "Loan from Family / Friends"),
    ("other", "Other Liability"),
]

GROUP_ORDER = list(dict.fromkeys(g for g, *_ in ASSET_TYPES))

ASSET_TYPE_MAP = {k: {"group": g, "key": k, "label": l, "weights": w} for g, k, l, w in ASSET_TYPES}
LIABILITY_TYPE_MAP = dict(LIABILITY_TYPES)
CATEGORY_LABELS = {c["key"]: c["label"] for c in CATEGORIES}


def weights_for(asset_type: str) -> dict:
    return ASSET_TYPE_MAP.get(asset_type, {"weights": {"other": 1}})["weights"]


def meta() -> dict:
    return {
        "categories": CATEGORIES,
        "asset_types": [
            {"group": g, "key": k, "label": l, "weights": w} for g, k, l, w in ASSET_TYPES
        ],
        "liability_types": [{"key": k, "label": l} for k, l in LIABILITY_TYPES],
        "risk_profiles": ["conservative", "moderate", "aggressive"],
    }
