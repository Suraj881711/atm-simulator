# 🏧 ATM Simulator

A small Flask web app that simulates an ATM: log in with a PIN, check
your balance, deposit and withdraw money, and view your transaction
history. Built to practise OOP (an `ATM` class) and Flask routing —
there is no real bank connection and no machine-learning model in this
project.

## Demo

- Open the app and log in with the demo PIN: **8817**
  (starting balance ₹5,00,000, a single shared demo account)
- Actions: **Check Balance**, **Deposit**, **Withdraw**,
  **Transaction History**, plus Logout

## Fixes & upgrades in this version

- **Negative-withdrawal bug fixed:** the original `withdraw()` only
  checked `amount <= balance`, so withdrawing a *negative* amount
  silently *increased* the balance. Amounts must now be positive.
- **Login actually protects the dashboard:** previously `/dashboard`
  could be opened directly without entering a PIN. It now requires a
  logged-in session (and Logout works).
- **Transaction history added:** every deposit/withdrawal is logged with
  the running balance and can be viewed from the dashboard.
- Current balance is always shown on the dashboard.
- The two `.lb` files in the original folder were **0-byte empty
  files**, not models — they have been removed.

## Tech stack

- Python, Flask (sessions), Bootstrap 5 pages

## How to run

```bash
pip install -r requirements.txt
python atm_app.py
```

Open http://127.0.0.1:5000 and log in with PIN 8817.

## Files

- `atm_app.py` — Flask app + `ATM` class (routes `/`, `/dashboard`,
  `/logout`, `/health`)
- `ATM.ipynb` — the original console (notebook) version of the ATM
  class (its PIN is 1325; the web app's PIN is 8817, as in the original
  web code)
- `templates/login.html`, `templates/dashboard.html`

## Note

The balance is one shared in-memory demo account (as in the original
code) — it resets when the server restarts and is shared by everyone
using the app. This is a learning project, not a real banking system.
