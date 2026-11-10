"""Tests for the advanced ATM simulator — run with: pytest test_app.py

Uses Flask's test client against a throwaway SQLite database, so the
real atm.db is never touched.
"""
import pytest

import atm_app
from atm_app import ATM


@pytest.fixture()
def bank(tmp_path):
    return ATM(str(tmp_path / "test_atm.db"))


@pytest.fixture()
def client(bank, monkeypatch):
    monkeypatch.setattr(atm_app, "atm", bank)
    atm_app.app.config["TESTING"] = True
    with atm_app.app.test_client() as c:
        yield c


def make_account(bank, name="Asha", pin="1234", opening=0.0):
    acc, err = bank.create_account(name, pin, opening)
    assert err is None
    return acc


def login(client, acc, pin="1234"):
    return client.post("/", data={"account_number": acc, "pin": pin},
                       follow_redirects=True)


# ---------------------------------------------------------------- accounts
def test_create_account_and_pin_is_hashed(bank):
    acc = make_account(bank, opening=1000)
    assert acc and len(acc) == 8
    row = bank.get_account(acc)
    assert row["balance"] == 1000.0
    # PIN must never be stored in plaintext
    assert "1234" not in row["pin_hash"]
    assert "$" in row["pin_hash"]  # salt$hash format


def test_create_account_rejects_bad_pin(bank):
    acc, err = bank.create_account("Bob", "12", 0)
    assert acc is None and "4 digits" in err


def test_login_success_and_failure(client, bank):
    acc = make_account(bank)
    resp = login(client, acc)
    assert b"Welcome Asha" in resp.data
    client.get("/logout")
    resp = login(client, acc, pin="9999")
    assert b"Incorrect PIN" in resp.data


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 302  # redirected to login


# ------------------------------------------------------------ money movement
def test_deposit_and_balance(client, bank):
    acc = make_account(bank, opening=500)
    login(client, acc)
    resp = client.post("/dashboard",
                       data={"action": "deposit", "amount": "250"})
    assert b"Deposited" in resp.data
    assert bank.check_balance(acc) == 750.0


def test_withdraw_validation(client, bank):
    acc = make_account(bank, opening=1000)
    login(client, acc)
    # negative amount (the original bug) must be rejected
    resp = client.post("/dashboard",
                       data={"action": "withdraw", "amount": "-100"})
    assert b"positive" in resp.data
    assert bank.check_balance(acc) == 1000.0
    # more than the balance
    resp = client.post("/dashboard",
                       data={"action": "withdraw", "amount": "2000"})
    assert b"Insufficient balance" in resp.data
    # valid withdrawal
    resp = client.post("/dashboard",
                       data={"action": "withdraw", "amount": "400"})
    assert b"Withdrawn" in resp.data
    assert bank.check_balance(acc) == 600.0


def test_withdraw_per_transaction_limit(client, bank):
    acc = make_account(bank, opening=200000)
    login(client, acc)
    resp = client.post("/dashboard",
                       data={"action": "withdraw", "amount": "60000"})
    assert b"Per-transaction limit" in resp.data
    assert bank.check_balance(acc) == 200000.0


def test_withdraw_daily_limit(client, bank):
    acc = make_account(bank, opening=500000)
    login(client, acc)
    for _ in range(2):  # 2 x 50,000 = the full ₹1,00,000 daily limit
        resp = client.post("/dashboard",
                           data={"action": "withdraw", "amount": "50000"})
        assert b"Withdrawn" in resp.data
    resp = client.post("/dashboard",
                       data={"action": "withdraw", "amount": "1"})
    assert b"Daily limit" in resp.data
    assert bank.check_balance(acc) == 400000.0


def test_transfer_moves_money_and_writes_both_ledger_entries(client, bank):
    sender = make_account(bank, "Sender", "1111", opening=5000)
    receiver = make_account(bank, "Receiver", "2222", opening=1000)
    login(client, sender, pin="1111")
    resp = client.post("/dashboard", data={
        "action": "transfer", "to_account": receiver, "amount": "1500"})
    assert b"Transferred" in resp.data
    assert bank.check_balance(sender) == 3500.0
    assert bank.check_balance(receiver) == 2500.0
    sender_types = [t["type"] for t in bank.history(sender)]
    receiver_types = [t["type"] for t in bank.history(receiver)]
    assert "Transfer Out" in sender_types
    assert "Transfer In" in receiver_types


def test_transfer_rejects_self_and_unknown(client, bank):
    acc = make_account(bank, opening=5000)
    login(client, acc)
    resp = client.post("/dashboard", data={
        "action": "transfer", "to_account": acc, "amount": "100"})
    assert b"own account" in resp.data
    resp = client.post("/dashboard", data={
        "action": "transfer", "to_account": "99999999", "amount": "100"})
    assert b"not found" in resp.data
    assert bank.check_balance(acc) == 5000.0  # nothing moved


# ------------------------------------------------------- statement & history
def test_mini_statement_and_history_page(client, bank):
    acc = make_account(bank, opening=1000)
    login(client, acc)
    client.post("/dashboard", data={"action": "deposit", "amount": "500"})
    client.post("/dashboard", data={"action": "withdraw", "amount": "200"})
    statement = bank.mini_statement(acc)
    assert len(statement) == 3  # opening deposit + deposit + withdraw
    assert statement[0]["type"] == "Withdraw"  # newest first
    resp = client.get("/dashboard")
    assert b"Mini Statement" in resp.data
    resp = client.get("/history")
    assert resp.status_code == 200
    assert b"Transaction History" in resp.data


# ------------------------------------------------------------------ security
def test_lockout_after_five_wrong_pins(client, bank):
    acc = make_account(bank)
    for _ in range(5):
        login(client, acc, pin="9999")
    assert bank.get_account(acc)["locked"] == 1
    # even the correct PIN is now refused
    resp = login(client, acc, pin="1234")
    assert b"locked" in resp.data.lower()


def test_change_pin(client, bank):
    acc = make_account(bank)
    login(client, acc)
    resp = client.post("/dashboard", data={
        "action": "change_pin", "old_pin": "1234", "new_pin": "4321"})
    assert b"PIN changed" in resp.data
    client.get("/logout")
    resp = login(client, acc, pin="4321")
    assert b"Welcome Asha" in resp.data
    # wrong old PIN is rejected
    resp = client.post("/dashboard", data={
        "action": "change_pin", "old_pin": "0000", "new_pin": "5555"})
    assert b"incorrect" in resp.data.lower()


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
