# Net Worth Tracker (India)

A self-hosted web app for tracking your assets, liabilities and net worth. Built for Indian investors: real estate, mutual funds, stocks, gold, FDs, PPF/EPF/NPS, insurance policies, crypto and more.

Everything runs locally in Docker. Your data is kept in a SQLite file on your own machine and never leaves it. The app needs no internet connection and has no third-party trackers.

## Features

- **Assets in groups:** Real Estate, Mutual Funds, Stocks, Gold & Silver, Fixed Income, Cash, Crypto, Insurance, Other. Pick a type from the dropdown, for example "Mutual Fund – ELSS" or "Sovereign Gold Bonds".
- **Every purchase and sale is recorded.** Monthly investments and yearly premiums can be added in one go as recurring entries.
- **Market value updates.** The latest value counts as the current value, and every update is kept as history.
- **Liabilities:** home, car and personal loans, credit cards, and money owed to family. Each has a rate, EMI, start date, tenure, outstanding balance and repaid %.
- **Dashboard:**
  - net worth
  - allocation by segment (donut chart) and by group (bars)
  - an **invested vs current value** chart, with the growth % at each value update, for all assets or a single one
  - **net worth over time**
- **Insights:** a target allocation based on your age and risk profile, plus rule-based recommendations:
  - emergency fund
  - real estate concentration
  - crypto limit
  - expensive debt
  - EMI-to-income ratio
  - PPF/EPF/NPS
  - insurance
  - tax notes for FY 2025-26
- **XIRR** for every asset.
- **Sortable tables** and collapsible groups.
- **Excel sync:**
  - The app keeps `data/networth.xlsx` up to date.
  - You can also edit the file in Excel and load the changes back; the app shows exactly what will change before applying anything.
- **Exports:** Excel workbook, Word (`.docx`) report, and JSON backup and restore.
- **Accounts:** anyone can sign up in the browser, and every account has its own private portfolio. The owner can turn sign-up off.
- **Security:**
  - login with salted scrypt password hashes
  - server-side sessions with idle and absolute timeouts
  - lockout after repeated wrong passwords
  - CSRF protection, a strict Content-Security-Policy, and no caching of financial data
  - a hardened container (read-only filesystem, non-root user, no Linux capabilities)
  - access only from the same computer by default

## Quick start

You need Docker (Docker Desktop on macOS or Windows).

```bash
git clone https://github.com/ravdy/networth.git
cd networth
docker compose up -d --build
```

Open **http://localhost:8080** and create your account. The first visit asks for a username (an email address works) and a password of at least 10 characters. Use `http`, not `https`.

```bash
docker compose down        # stop (your data is kept)
docker compose up -d       # start again
```

## Try the demo (fake data)

A separate demo instance runs with 10 years of fictional history, so you can explore the app without entering anything real:

```bash
docker compose -f docker-compose.demo.yml up -d --build
docker compose -f docker-compose.demo.yml exec -T networth-demo python - < demo/seed_demo.py
```

Open **http://localhost:8081** and sign in with one of these sample accounts, or click **Create an account** to get your own copy of the sample portfolio:

| Username | Password |
|---|---|
| `demo` | `demo-2026-show` |
| `demouser@gmail.com` | `DemoUser@2026` |

Running the second command again resets the demo: it deletes every demo account and restores these two with fresh data.

The demo uses its own container, port and folder (`demo-data/`). The seed script refuses to run anywhere except in the demo container, so it can't overwrite real data.

```bash
docker compose -f docker-compose.demo.yml down
```

## Accounts

Each account has its own **private portfolio**: assets, liabilities, profile, history, Excel file and exports. One account can never see or change another account's data.

### Create an account (sign up)

1. Open the app (http://localhost:8080) in the browser.
2. On the sign-in page, click **Create an account**. You can also go straight to `http://localhost:8080/login#register`.
3. Enter a username (3–60 characters; letters, numbers and `. _ @ + -`, so an email address works) and a password of at least 10 characters, twice.
4. Click **Create account**. You're signed in to your new, empty portfolio. In the demo, it starts with a copy of the sample data.

The very first account created on a fresh install also takes over any data that was entered before accounts existed.

### Sign in and out

Use **Sign in** on the same page. **Log out** is at the top right of the app. **Settings → Account & security** shows who is signed in and lets you change your password.

### Manage accounts (server owner)

```bash
docker compose exec networth python -m app.auth list                 # list accounts
docker compose exec -it networth python -m app.auth reset <username>  # set a new password
```

To stop new sign-ups (for example, once everyone in your family has an account), add `NETWORTH_ALLOW_SIGNUP: "0"` under `environment:` in `docker-compose.yml`, then run `docker compose up -d`. The first account can always be created, even with sign-up off. New sign-ups are also limited to 20 per hour (`NETWORTH_SIGNUPS_PER_HOUR`).

## Your data

- **Database:** a single SQLite file, `data/networth.db`, holding every account's data. It is created on first run and kept on your machine, not inside Docker, so it survives container rebuilds and Docker resets.
- **Excel files:** the first account uses `data/networth.xlsx`; other accounts use `data/networth-user<id>.xlsx`.
- **Automatic backups:**
  - `data/backups/`: one per day, keeping the last 30
  - an extra copy before every import or Excel load
- **Manual backup:**
  - **Settings → Export backup (JSON)** saves the signed-in account's data. **Import backup** replaces only that account's data.
  - Copying the `data/` folder backs up every account.
- **Restore a backup:**

  ```bash
  docker compose stop
  cp data/backups/networth-YYYY-MM-DD-daily.db data/networth.db
  docker compose start
  ```

`data/` and `demo-data/` are listed in `.gitignore`, so your financial data is never committed.

## Security

- **Sign-in** is required for every page, export and download. Each account sees only its own data. Every request is checked against the signed-in account, and an ID belonging to someone else is treated as "not found".
  - Sessions end after 60 minutes idle, after 12 hours, or when the browser closes.
  - Change the limits with `NETWORTH_IDLE_MINUTES` and `NETWORTH_SESSION_HOURS` in `docker-compose.yml`.
  - Five wrong passwords lock the login for a while.
- **Local only:** the app listens on `127.0.0.1`, so other devices on your network can't reach it.
- **Container:** read-only filesystem, all Linux capabilities dropped, `no-new-privileges`, non-root user.
- **Disk encryption:** turn on full-disk encryption (FileVault on macOS, BitLocker on Windows). The database, backups and Excel file are only as safe as the disk they're on.

**Forgot your password?**

```bash
docker compose exec -it networth python -m app.auth reset <username>
```

This sets a new password and signs out all of that account's sessions. With only one account, the username can be left out.

## Using it

1. **Settings:** enter your age, risk profile, monthly expenses, income and tax regime. The recommendations depend on these.
2. **Assets → + Add asset:** choose the type, then enter the purchase date and amount.
3. **Buy / Sell** records further purchases, for example a monthly SIP or a yearly insurance premium. **Recurring** adds a whole series of payments at once.
4. **Update value** records the current market value. Each update becomes a point on the growth chart.
5. **Liabilities:** add loans and cards, and use **Update balance** as you repay them.
6. **Excel:**
   - **Export to Excel** downloads the workbook.
   - **Settings → Excel sync** loads edits you make in `data/networth.xlsx`.

## How the numbers work

- **Net invested** = purchases − sales.
- **Current value** = latest market value + any purchases or sales made after it. If you never update the value, it equals net invested.
- **XIRR** is the annualised return, worked out from the dates of your cash flows.
- **Allocation segments:**
  - Equity, Debt, Real Estate, Gold & Silver, Cash, Crypto, Other
  - hybrid funds count as 65% equity and 35% debt
  - NPS counts as 50% equity and 50% debt
  - insurance policies (surrender value) count as debt
- **Target allocation** applies only to financial assets, so real estate is judged separately:
  - equity: 100 − age, then −15 (conservative), +0 (moderate) or +10 (aggressive)
  - gold: 8–12%
  - crypto: 0–5%
  - cash: 5–7%
  - debt: whatever is left

The guidance uses common rules of thumb and is **not financial advice**.

## Develop without Docker

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

| Path | What it does |
|---|---|
| [app/main.py](app/main.py) | FastAPI routes, auth and security middleware |
| [app/portfolio.py](app/portfolio.py) | valuation, XIRR, allocation, growth series |
| [app/recommendations.py](app/recommendations.py) | recommendation rules |
| [app/catalog.py](app/catalog.py) | asset and liability types and their segment weights |
| [app/excel.py](app/excel.py) | Excel export and three-way sync |
| [app/report.py](app/report.py) | Word report |
| [app/auth.py](app/auth.py) | accounts, sign-up, password hashing, sessions, lockout |
| [app/db.py](app/db.py) | SQLite schema and backups |
| [app/static/](app/static/) | UI: plain HTML/CSS/JS, no build step |
| [app/demo_data.py](app/demo_data.py) | fictional sample portfolio for the demo |
| [demo/seed_demo.py](demo/seed_demo.py) | resets the demo instance |
