"""Ledger reconciliation: verify user balances against the double-entry ledger.

Run on demand from the admin System tab. The report checks:
  1. Per-user balance equals the sum of that user's ledger entries.
  2. Every transaction's ledger batch sums to zero (double-entry invariant).
  3. The global ledger sums to zero (money is conserved).

Report-only by design — reconciliation detects drift; fixing balances is an
operator decision, never an automatic one.
"""

from decimal import Decimal
from typing import Any

if __package__:
    from .database import get_db, init_db
else:
    from database import get_db, init_db  # type: ignore[no-redef]


class ReconciliationManager:
    def __init__(self):
        init_db()

    def reconcile(self) -> dict:
        """Run all reconciliation checks. Returns a report dict."""
        report: dict[str, Any] = {
            "checked_users": 0,
            "balance_mismatches": [],
            "unbalanced_transactions": [],
            "ledger_total": "0",
            "users_total": "0",
            "system_accounts_total": "0",
            "ok": True,
        }
        system_accounts = {"SYSTEM_CASH", "SYSTEM_REVENUE", "BILLER_SYSTEM"}
        with get_db() as conn:
            cursor = conn.cursor()

            # 1. Sum ledger entries per account
            ledger_sums: dict[str, Decimal] = {}
            txn_sums: dict[str, Decimal] = {}
            for row in cursor.execute("SELECT account_id, transaction_id, amount FROM ledger"):
                amount = Decimal(row["amount"])
                ledger_sums[row["account_id"]] = ledger_sums.get(row["account_id"], Decimal("0")) + amount
                txn_sums[row["transaction_id"]] = txn_sums.get(row["transaction_id"], Decimal("0")) + amount

            # 2. Per-user balance vs ledger sum
            users_total = Decimal("0")
            for row in cursor.execute("SELECT phone, balance FROM users"):
                actual = Decimal(row["balance"])
                users_total += actual
                expected = ledger_sums.get(row["phone"], Decimal("0"))
                report["checked_users"] += 1
                if actual != expected:
                    report["balance_mismatches"].append({
                        "phone": row["phone"],
                        "balance": str(actual),
                        "ledger_sum": str(expected),
                        "difference": str(actual - expected),
                    })

            # 3. Per-transaction batches must sum to zero
            for txn_id, total in txn_sums.items():
                if total != Decimal("0"):
                    report["unbalanced_transactions"].append({
                        "transaction_id": txn_id, "sum": str(total)})

            # 4. Global invariants
            ledger_total = sum(ledger_sums.values(), Decimal("0"))
            system_total = sum(
                (amt for acct, amt in ledger_sums.items() if acct in system_accounts),
                Decimal("0"))
            report["ledger_total"] = str(ledger_total)
            report["users_total"] = str(users_total)
            report["system_accounts_total"] = str(system_total)

            # Money conservation: user balances are exactly offset by the
            # system accounts (cash/revenue/biller float).
            if ledger_total != Decimal("0"):
                report["ok"] = False
            if users_total + system_total != Decimal("0"):
                report["ok"] = False
            if report["balance_mismatches"] or report["unbalanced_transactions"]:
                report["ok"] = False
        return report
