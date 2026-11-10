# 🏧 ATM Simulator — Advanced

A full multi-account ATM / mini-banking web app built with Flask and
SQLite. Unlike a simple demo, this version behaves like a real (small)
banking system: anyone can open an account, log in with an account
number + PIN, deposit, withdraw, transfer money to other accounts and
see a permanent transaction history. There is no real bank connection
and no machine-learning model in this project — the "advanced" part is
real persistence, real authentication and real transaction rules.

## Features

- **Create account** — name + 4-digit PIN (+ optional opening deposit);
  the app issues an 8-digit account number
- **Secure PIN storage** — PINs are stored only as salted
  PBKDF2-HMAC-SHA256 hashes (100,000 iterations), never in plain text
- **Login / logout** — session-based login by account number + PIN;
  every protected page requires a logged-in session
- **Deposit & withdraw** — validated amounts (positive, sufficient
  balance), with a **₹50,000 per-transaction limit** and a
  **₹1,00,000 daily limit** on money out (withdrawals + transfers),
  enforced from the transaction ledger
- **Transfer money** — send money to any other account number; the
  transfer is **atomic** (both balances and both ledger entries are
  written in a single database transaction, so a failure rolls
  everything back). Self-transfers and unknown accounts are rejected
- **Mini statement** — last 10 transactions on the dashboard, straight
  from the ledger
- **Full transaction history page** — every transaction ever made on
  the account, newest first, with running balances
- **Change PIN** — the current PIN must be verified first
- **Account lockout** — after **5 wrong PIN attempts** the account is
  locked (even the correct PIN is then refused) with a clear message
- **SQLite persistence** — accounts and the transaction ledger survive
  server restarts (`atm.db`, created automatically at first run)

## What's advanced in this version

The original version was a single shared in-memory account with one
hardcoded PIN and a balance that reset on every restart. This version
replaces that with:

- A real **SQLite database** (stdlib `sqlite3`) with `accounts` and
  `transactions` tables — the ledger is the source of truth for
  statements and for the daily-limit check
- **Hashed PINs** (`hashlib.pbkdf2_hmac` with a per-account random
  salt) instead of a PIN compared in plain text
- **Per-account sessions** — each user sees only their own balance and
  history
- **Atomic transfers** using a single DB transaction
  (`BEGIN IMMEDIATE` … commit/rollback)
- **Bank-style rules**: per-transaction limit, daily limit, failed-login
  lockout, PIN change with old-PIN verification
- The older fixes are kept: the negative-withdrawal bug (a negative
  amount silently *increased* the balance) stays fixed, and the
  dashboard cannot be opened without logging in
- A **pytest test-suite** (`test_app.py`, 14 tests) covering account
  creation, login, deposit/withdraw validation, both limits, transfers,
  statements, PIN change and lockout

## Tech stack

- Python, Flask (sessions, Jinja templates), SQLite (stdlib `sqlite3`)
- `hashlib` / `hmac` / `secrets` (stdlib) for PIN hashing
- Bootstrap 5 pages (CDN), pytest for tests

## How to run

```bash
pip install -r requirements.txt
python atm_app.py
```

Open http://127.0.0.1:5000 — create an account, note the account
number, then log in with it and your PIN.

Run the tests with:

```bash
pip install pytest
pytest test_app.py
```

## Files

- `atm_app.py` — Flask app + `ATM` class (SQLite bank + ledger;
  routes `/`, `/create`, `/dashboard`, `/history`, `/logout`,
  `/health`)
- `test_app.py` — pytest suite (Flask test client, throwaway DB)
- `ATM.ipynb` — the original console (notebook) version of the ATM
  class, kept as-is
- `templates/login.html`, `templates/create.html`,
  `templates/dashboard.html`, `templates/history.html`
- `atm.db` — created at runtime (git-ignored, not shipped)

## Note

This is a learning project that simulates a bank's core rules; it is
not connected to any real bank and should not be used with real money
or real PINs.
