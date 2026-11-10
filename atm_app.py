# atm_web_app.py — Advanced ATM Simulator
#
# Upgrades over the original single-account demo:
#   * Real multi-account banking backed by SQLite (stdlib sqlite3)
#   * PINs stored as salted PBKDF2-HMAC-SHA256 hashes — never plaintext
#   * Create-account flow, login by account number + PIN, session auth
#   * Deposit / withdraw with validation, per-transaction and daily limits
#   * Atomic transfers between accounts, mini statement + full history
#     from a permanent transaction ledger
#   * Change PIN, and account lockout after 5 wrong PIN attempts
#
# The `ATM` class and its core method names (authenticate, deposit,
# withdraw, check_balance) are kept from the original code; they now
# operate on real per-account rows instead of one in-memory balance.
import hashlib
import hmac
import os
import secrets
import sqlite3

from flask import (Flask, jsonify, redirect, render_template, request,
                   session, url_for)

app = Flask(__name__)
app.secret_key = os.environ.get("ATM_SECRET_KEY", "atm-simulator")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ATM_DB_PATH", os.path.join(BASE_DIR, "atm.db"))

# Limits (₹)
PER_TRANSACTION_LIMIT = 50000.0
DAILY_LIMIT = 100000.0
MAX_PIN_ATTEMPTS = 5
PBKDF2_ITERATIONS = 100_000


def _hash_pin(pin, salt=None):
    """Return 'salt$hash' for a PIN using PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(pin).encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex() + "$" + digest.hex()


def _verify_pin(pin, stored):
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(pin).encode("utf-8"), bytes.fromhex(salt_hex),
        PBKDF2_ITERATIONS)
    return hmac.compare_digest(digest.hex(), hash_hex)


class ATM:
    """A SQLite-backed bank of ATM accounts with a transaction ledger."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    # -- database plumbing -------------------------------------------------
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_number TEXT PRIMARY KEY,
                    name           TEXT NOT NULL,
                    pin_hash       TEXT NOT NULL,
                    balance        REAL NOT NULL DEFAULT 0,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    locked         INTEGER NOT NULL DEFAULT 0,
                    created_at     TEXT NOT NULL
                        DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_number TEXT NOT NULL,
                    type           TEXT NOT NULL,
                    amount         REAL NOT NULL,
                    balance_after  REAL NOT NULL,
                    note           TEXT DEFAULT '',
                    created_at     TEXT NOT NULL
                        DEFAULT (datetime('now', 'localtime'))
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _record(self, conn, account_number, txn_type, amount,
                balance_after, note=""):
        conn.execute(
            "INSERT INTO transactions "
            "(account_number, type, amount, balance_after, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_number, txn_type, amount, balance_after, note))

    # -- accounts ----------------------------------------------------------
    def create_account(self, name, pin, opening_deposit=0.0):
        """Create an account. Returns (account_number, error_message)."""
        name = (name or "").strip()
        if not name:
            return None, "❌ Please enter the account holder's name."
        if not (pin and len(str(pin)) == 4 and str(pin).isdigit()):
            return None, "❌ PIN must be exactly 4 digits."
        if opening_deposit is None or opening_deposit < 0:
            return None, "❌ Opening deposit cannot be negative."

        conn = self._connect()
        try:
            cur = conn.execute(
                "INSERT INTO accounts (account_number, name, pin_hash, "
                "balance) VALUES ('PENDING', ?, ?, ?)",
                (name, _hash_pin(pin), round(float(opening_deposit), 2)))
            account_number = str(10000000 + cur.lastrowid)
            conn.execute(
                "UPDATE accounts SET account_number = ? WHERE rowid = ?",
                (account_number, cur.lastrowid))
            if opening_deposit:
                self._record(conn, account_number, "Deposit",
                             round(float(opening_deposit), 2),
                             round(float(opening_deposit), 2),
                             "Opening deposit")
            conn.commit()
            return account_number, None
        finally:
            conn.close()

    def get_account(self, account_number):
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM accounts WHERE account_number = ?",
                (str(account_number),)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def authenticate(self, account_number, entered_pin):
        """Check a PIN. Returns (status, message) where status is one of
        'ok', 'invalid', 'locked', 'not_found'. Wrong PINs are counted and
        the account locks after MAX_PIN_ATTEMPTS failures."""
        account = self.get_account(account_number)
        if account is None:
            return "not_found", "❌ Account not found."
        if account["locked"]:
            return ("locked",
                    "🔒 This account is locked after too many wrong PIN "
                    "attempts. Please visit your branch to unlock it.")
        if _verify_pin(entered_pin, account["pin_hash"]):
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE accounts SET failed_attempts = 0 "
                    "WHERE account_number = ?", (account["account_number"],))
                conn.commit()
            finally:
                conn.close()
            return "ok", "✅ Login successful."

        attempts = account["failed_attempts"] + 1
        locked = 1 if attempts >= MAX_PIN_ATTEMPTS else 0
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE accounts SET failed_attempts = ?, locked = ? "
                "WHERE account_number = ?",
                (attempts, locked, account["account_number"]))
            conn.commit()
        finally:
            conn.close()
        if locked:
            return ("locked",
                    "🔒 Too many wrong PIN attempts — this account is "
                    "now locked. Please visit your branch to unlock it.")
        remaining = MAX_PIN_ATTEMPTS - attempts
        return ("invalid",
                f"❌ Incorrect PIN. {remaining} attempt(s) left before "
                "the account locks.")

    # -- money movement ----------------------------------------------------
    def check_balance(self, account_number):
        account = self.get_account(account_number)
        return account["balance"] if account else None

    def _daily_outgoing(self, conn, account_number):
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
            "WHERE account_number = ? AND type IN ('Withdraw', 'Transfer Out') "
            "AND date(created_at) = date('now', 'localtime')",
            (account_number,)).fetchone()
        return row["total"]

    def _validate_outgoing(self, conn, account_number, amount, balance):
        """Shared withdraw/transfer validation. Returns error or None."""
        if amount is None or amount <= 0:
            return "❌ Amount must be a positive number."
        if amount > PER_TRANSACTION_LIMIT:
            return (f"❌ Per-transaction limit is "
                    f"₹{PER_TRANSACTION_LIMIT:,.0f}.")
        if amount > balance:
            return "❌ Insufficient balance."
        if self._daily_outgoing(conn, account_number) + amount > DAILY_LIMIT:
            return (f"❌ Daily limit of ₹{DAILY_LIMIT:,.0f} would be "
                    "exceeded (withdrawals + transfers out).")
        return None

    def deposit(self, account_number, amount):
        if amount is None or amount <= 0:
            return "❌ Invalid deposit amount."
        amount = round(float(amount), 2)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT balance FROM accounts WHERE account_number = ?",
                (account_number,)).fetchone()
            if row is None:
                return "❌ Account not found."
            new_balance = round(row["balance"] + amount, 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE account_number = ?",
                (new_balance, account_number))
            self._record(conn, account_number, "Deposit", amount,
                         new_balance)
            conn.commit()
            return f"✅ Deposited ₹{amount:,.2f} successfully."
        finally:
            conn.close()

    def withdraw(self, account_number, amount):
        # The original bug (negative withdrawal increasing the balance)
        # stays fixed: _validate_outgoing rejects amount <= 0 first.
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT balance FROM accounts WHERE account_number = ?",
                (account_number,)).fetchone()
            if row is None:
                return "❌ Account not found."
            error = self._validate_outgoing(
                conn, account_number,
                None if amount is None else float(amount), row["balance"])
            if error:
                return error
            amount = round(float(amount), 2)
            new_balance = round(row["balance"] - amount, 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE account_number = ?",
                (new_balance, account_number))
            self._record(conn, account_number, "Withdraw", amount,
                         new_balance)
            conn.commit()
            return f"✅ Withdrawn ₹{amount:,.2f} successfully."
        finally:
            conn.close()

    def transfer(self, from_account, to_account, amount):
        """Move money between accounts atomically: both balance updates
        and both ledger entries happen in a single DB transaction, so a
        failure anywhere rolls everything back."""
        from_account, to_account = str(from_account), str(to_account or "")
        if from_account == to_account:
            return "❌ You cannot transfer money to your own account."
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            sender = conn.execute(
                "SELECT balance FROM accounts WHERE account_number = ?",
                (from_account,)).fetchone()
            receiver = conn.execute(
                "SELECT balance FROM accounts WHERE account_number = ?",
                (to_account,)).fetchone()
            if sender is None:
                conn.rollback()
                return "❌ Your account could not be found."
            if receiver is None:
                conn.rollback()
                return "❌ Beneficiary account not found."
            error = self._validate_outgoing(
                conn, from_account,
                None if amount is None else float(amount), sender["balance"])
            if error:
                conn.rollback()
                return error
            amount = round(float(amount), 2)
            sender_new = round(sender["balance"] - amount, 2)
            receiver_new = round(receiver["balance"] + amount, 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE account_number = ?",
                (sender_new, from_account))
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE account_number = ?",
                (receiver_new, to_account))
            self._record(conn, from_account, "Transfer Out", amount,
                         sender_new, f"To account {to_account}")
            self._record(conn, to_account, "Transfer In", amount,
                         receiver_new, f"From account {from_account}")
            conn.commit()
            return (f"✅ Transferred ₹{amount:,.2f} to account "
                    f"{to_account} successfully.")
        finally:
            conn.close()

    def change_pin(self, account_number, old_pin, new_pin):
        account = self.get_account(account_number)
        if account is None:
            return "❌ Account not found."
        if not _verify_pin(old_pin, account["pin_hash"]):
            return "❌ Current PIN is incorrect."
        if not (new_pin and len(str(new_pin)) == 4 and str(new_pin).isdigit()):
            return "❌ New PIN must be exactly 4 digits."
        if str(new_pin) == str(old_pin):
            return "❌ New PIN must be different from the current PIN."
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE accounts SET pin_hash = ? WHERE account_number = ?",
                (_hash_pin(new_pin), account_number))
            conn.commit()
            return "✅ PIN changed successfully."
        finally:
            conn.close()

    # -- statements ----------------------------------------------------------
    def mini_statement(self, account_number, limit=10):
        return self.history(account_number, limit=limit)

    def history(self, account_number, limit=None):
        conn = self._connect()
        try:
            sql = ("SELECT type, amount, balance_after, note, created_at "
                   "FROM transactions WHERE account_number = ? "
                   "ORDER BY id DESC")
            params = [account_number]
            if limit:
                sql += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# One ATM (bank) instance for the whole app, as in the original code —
# but now it is backed by a database instead of a single in-memory balance.
atm = ATM(DB_PATH)


def _logged_in_account():
    return session.get("account_number")


@app.route("/", methods=["GET", "POST"])
def login():
    if _logged_in_account():
        return redirect(url_for("dashboard"))
    error = ""
    if request.method == "POST":
        account_number = request.form.get("account_number", "").strip()
        pin = request.form.get("pin", "")
        status, message = atm.authenticate(account_number, pin)
        if status == "ok":
            account = atm.get_account(account_number)
            session["logged_in"] = True
            session["account_number"] = account["account_number"]
            session["name"] = account["name"]
            return redirect(url_for("dashboard"))
        error = message
    return render_template("login.html", error=error)


@app.route("/create", methods=["GET", "POST"])
def create_account():
    message, error, new_account = "", "", None
    if request.method == "POST":
        name = request.form.get("name", "")
        pin = request.form.get("pin", "")
        confirm_pin = request.form.get("confirm_pin", "")
        opening = request.form.get("opening_deposit", type=float)
        if pin != confirm_pin:
            error = "❌ PIN and Confirm PIN do not match."
        else:
            new_account, error = atm.create_account(
                name, pin, opening if opening is not None else 0.0)
            if new_account:
                message = (f"✅ Account created successfully! Your account "
                           f"number is {new_account}. Keep it safe — you "
                           "need it with your PIN to log in.")
    return render_template("create.html", message=message, error=error,
                           new_account=new_account)


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    account_number = _logged_in_account()
    if not account_number:
        return redirect(url_for("login"))

    message = ""
    if request.method == "POST":
        action = request.form.get("action")
        amount = request.form.get("amount", type=float)
        if action == "deposit":
            message = atm.deposit(account_number, amount)
        elif action == "withdraw":
            message = atm.withdraw(account_number, amount)
        elif action == "transfer":
            message = atm.transfer(
                account_number,
                request.form.get("to_account", "").strip(), amount)
        elif action == "change_pin":
            message = atm.change_pin(
                account_number, request.form.get("old_pin", ""),
                request.form.get("new_pin", ""))
        elif action == "balance":
            message = (f"💰 Balance: "
                       f"₹{atm.check_balance(account_number):,.2f}")
        else:
            message = "❌ Invalid action."

    account = atm.get_account(account_number)
    return render_template(
        "dashboard.html", name=account["name"],
        account_number=account_number, balance=account["balance"],
        message=message, statement=atm.mini_statement(account_number))


@app.route("/history")
def history_page():
    account_number = _logged_in_account()
    if not account_number:
        return redirect(url_for("login"))
    account = atm.get_account(account_number)
    return render_template(
        "history.html", name=account["name"],
        account_number=account_number, balance=account["balance"],
        history=atm.history(account_number))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
