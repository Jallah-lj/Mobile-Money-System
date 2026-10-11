"""Professionalism: ledger reconciliation — balances vs double-entry ledger."""

from decimal import Decimal

from mobile_money_system.database import get_db
from mobile_money_system.models import utcnow
from mobile_money_system.reconcile import ReconciliationManager


def test_clean_database_reconciles(managers, verified_user, second_verified_user):
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.transfer(alice, bob, 100)
    tm.withdraw(alice, 50)
    tm.pay_bill(alice, 20, "Water", "ACC-1")

    report = ReconciliationManager().reconcile()
    assert report["ok"] is True
    assert report["checked_users"] >= 2
    assert report["balance_mismatches"] == []
    assert report["unbalanced_transactions"] == []
    assert Decimal(report["ledger_total"]) == 0


def test_detects_balance_drift(managers, verified_user):
    alice, um, tm = verified_user
    tm.deposit(alice, 100)

    # Tamper: change the balance directly, bypassing the ledger
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = '99999' WHERE phone = ?", (alice,))
        conn.commit()

    report = ReconciliationManager().reconcile()
    assert report["ok"] is False
    mismatch = next(m for m in report["balance_mismatches"] if m["phone"] == alice)
    assert mismatch["balance"] == "99999"
    assert mismatch["difference"] != "0"


def test_detects_unbalanced_ledger_batch(managers, verified_user):
    alice, um, tm = verified_user
    tm.deposit(alice, 100)
    real_txn_id = tm.get_history(alice)[0].id  # a real txn (FK constraint)

    # Tamper: an extra entry makes the transaction's batch sum non-zero
    with get_db() as conn:
        conn.execute(
            "INSERT INTO ledger (id, transaction_id, account_id, amount, timestamp, description)"
            " VALUES ('LEG-TAMPER', ?, ?, '5', ?, 'tamper')",
            (real_txn_id, alice, utcnow().isoformat()))
        conn.commit()

    report = ReconciliationManager().reconcile()
    assert report["ok"] is False
    assert any(u["transaction_id"] == real_txn_id for u in report["unbalanced_transactions"])
    assert Decimal(report["ledger_total"]) != 0


def test_money_is_conserved(managers, verified_user, second_verified_user):
    """users_total + system_accounts_total == 0 on a healthy database."""
    from decimal import Decimal
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    tm.transfer(alice, bob, 250)
    report = ReconciliationManager().reconcile()
    assert Decimal(report["users_total"]) + Decimal(report["system_accounts_total"]) == 0
