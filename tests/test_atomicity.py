"""Reliability: atomic balance updates — no double-spend under concurrency.

Every money movement runs inside one SQLite write transaction (BEGIN IMMEDIATE):
the balance is re-read and re-checked under the write lock, so two racing
operations can never both spend the same money.
"""

import threading
from decimal import Decimal

from mobile_money_system.database import get_db


def test_concurrent_transfers_cannot_double_spend(managers, verified_user, second_verified_user):
    """Two threads race to transfer the entire balance: exactly one wins."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    # Alice has exactly 10000; both threads try to transfer all of it
    results = []
    barrier = threading.Barrier(2)

    def do_transfer():
        barrier.wait()  # line the threads up to maximize the race
        results.append(tm.transfer(alice, bob, 10000.0, "race"))

    t1 = threading.Thread(target=do_transfer)
    t2 = threading.Thread(target=do_transfer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [ok for ok, _ in results]
    assert successes.count(True) == 1
    assert successes.count(False) == 1

    alice_now = um.get_user(alice)
    bob_now = um.get_user(bob)
    assert alice_now.balance == Decimal("0")
    assert bob_now.balance == Decimal("10000")
    # Money is conserved: nothing was created or destroyed
    assert alice_now.balance + bob_now.balance == Decimal("10000")


def test_concurrent_withdrawals_respect_balance(managers, verified_user):
    """Four racing withdrawals of 4000 (+0.5% fee = 4020 each) from a 10000
    balance: exactly two succeed (2*4020 = 8040 <= 10000 < 3*4020)."""
    alice, um, tm = verified_user
    results = []
    barrier = threading.Barrier(4)

    def do_withdraw():
        barrier.wait()
        results.append(tm.withdraw(alice, 4000.0, "race"))

    threads = [threading.Thread(target=do_withdraw) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [ok for ok, _ in results]
    assert successes.count(True) == 2
    assert um.get_user(alice).balance == Decimal("10000") - 2 * Decimal("4020")


def test_failed_transfer_leaves_no_partial_state(managers, verified_user, second_verified_user):
    """A transfer rejected by the in-transaction funds check must not leave a
    transaction record, ledger entries, or a balance change behind."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    ok, _msg = tm.transfer(alice, bob, 999999.0, "too much")
    assert not ok

    with get_db() as conn:
        n_txn = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE description = 'too much'").fetchone()[0]
        ledger_total = conn.execute("SELECT SUM(CAST(amount AS REAL)) FROM ledger").fetchone()[0]
    assert n_txn == 0
    assert ledger_total == 0.0
    assert um.get_user(alice).balance == Decimal("10000")


def test_ledger_invariant_holds_after_racing_operations(managers, verified_user, second_verified_user):
    """The double-entry invariant (every batch sums to zero) holds even when
    operations race."""
    alice, um, tm = verified_user
    bob, _, _ = second_verified_user
    barrier = threading.Barrier(3)
    results = []

    def op(i):
        barrier.wait()
        if i == 0:
            results.append(tm.transfer(alice, bob, 100.0, "race"))
        elif i == 1:
            results.append(tm.withdraw(alice, 50.0, "race"))
        else:
            results.append(tm.pay_bill(alice, 20.0, "Water", "ACC-1", "race"))

    threads = [threading.Thread(target=op, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(ok for ok, _ in results)

    with get_db() as conn:
        ledger_total = conn.execute("SELECT SUM(CAST(amount AS REAL)) FROM ledger").fetchone()[0]
    assert ledger_total == 0.0
