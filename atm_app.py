# atm_web_app.py
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = 'atm-simulator'


# Simulated ATM class
class ATM:
    def __init__(self, balance):
        self.balance = balance
        self.pin = "8817"
        self.name = "User"
        self.history = []  # transaction log for this session of the ATM

    def authenticate(self, entered_pin):
        return entered_pin == self.pin

    def deposit(self, amount):
        if amount is not None and amount > 0:
            self.balance += amount
            self.history.insert(0, {
                'type': 'Deposit', 'amount': amount,
                'balance': self.balance})
            return f"✅ Deposited ₹{amount:.2f} successfully."
        return "❌ Invalid deposit amount."

    def withdraw(self, amount):
        # FIX: the original only checked amount <= balance, so a NEGATIVE
        # withdrawal silently increased the balance.
        if amount is None or amount <= 0:
            return "❌ Invalid withdrawal amount."
        if amount <= self.balance:
            self.balance -= amount
            self.history.insert(0, {
                'type': 'Withdraw', 'amount': amount,
                'balance': self.balance})
            return f"✅ Withdrawn ₹{amount:.2f} successfully."
        return "❌ Insufficient balance."

    def check_balance(self):
        return self.balance


# Create an ATM object (single shared demo account, as in the original)
atm = ATM(500000)


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pin = request.form.get("pin")
        if atm.authenticate(pin):
            session['logged_in'] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="❌ Incorrect PIN")
    return render_template("login.html")


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for("login"))

    message = ""
    show_history = False
    if request.method == "POST":
        action = request.form.get("action")
        amount = request.form.get("amount", type=float)

        if action == "balance":
            message = f"💰 Balance: ₹{atm.check_balance():.2f}"
        elif action == "deposit":
            message = atm.deposit(amount)
        elif action == "withdraw":
            message = atm.withdraw(amount)
        elif action == "history":
            show_history = True
        else:
            message = "❌ Invalid action or amount."

    return render_template("dashboard.html", name=atm.name,
                           balance=atm.check_balance(), message=message,
                           history=atm.history, show_history=show_history)


@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return {'status': 'ok'}


if __name__ == "__main__":
    app.run(debug=True)
