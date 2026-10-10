"""Scheduled & recurring payments (standing orders).

Users can schedule one-off future payments or recurring transfers/bill
payments (daily / weekly / monthly). The app ticks the scheduler on every
run; due rows are claimed atomically before execution so a payment can
never fire twice, and every run is recorded (last_run_at / last_status).

Failure policy: a failed execution deactivates the order (the user must
re-enable it) — this avoids silently retrying payments that will keep
failing (e.g. insufficient funds). 'once' orders deactivate after firing.
"""

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

try:
    from models import utcnow
    from database import get_db, init_db
    from users import UserManager
    from transactions import TransactionManager
    from audit import log_event
except ImportError:
    from mobile_money_system.models import utcnow
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.users import UserManager
    from mobile_money_system.transactions import TransactionManager
    from mobile_money_system.audit import log_event

FREQUENCIES = ("once", "daily", "weekly", "monthly")
PAYMENT_TYPES = ("TRANSFER", "BILL_PAYMENT")


def _next_run(frequency: str, from_time) -> Optional[str]:
    """ISO timestamp of the next occurrence after `from_time` (naive UTC)."""
    if frequency == "daily":
        return (from_time + timedelta(days=1)).isoformat()
    if frequency == "weekly":
        return (from_time + timedelta(weeks=1)).isoformat()
    if frequency == "monthly":
        # Month arithmetic without external dependencies
        year, month = from_time.year, from_time.month + 1
        if month > 12:
            year, month = year + 1, 1
        # Clamp the day to the target month's length
        import calendar
        day = min(from_time.day, calendar.monthrange(year, month)[1])
        return from_time.replace(year=year, month=month, day=day).isoformat()
    return None  # 'once' has no next run


class ScheduledPaymentManager:
    def __init__(self, user_manager: UserManager, transaction_manager: TransactionManager):
        self.user_manager = user_manager
        self.transaction_manager = transaction_manager
        init_db()  # Ensure schema exists (safe on fresh databases)

    def create(self, owner_phone: str, p_type: str, amount: float,
               description: str = "", receiver_phone: str = "",
               biller_name: str = "", biller_id: str = "",
               frequency: str = "once", start_at: Optional[str] = None) -> Tuple[bool, str]:
        """Create a scheduled payment. Returns (success, message)."""
        owner = self.user_manager.get_user(owner_phone)
        if not owner:
            return False, "User not found"
        if p_type not in PAYMENT_TYPES:
            return False, f"Invalid payment type (must be one of {PAYMENT_TYPES})"
        if frequency not in FREQUENCIES:
            return False, f"Invalid frequency (must be one of {FREQUENCIES})"
        try:
            amount_decimal = float(amount)
        except (TypeError, ValueError):
            return False, "Invalid amount"
        if amount_decimal <= 0:
            return False, "Amount must be greater than 0"

        if p_type == "TRANSFER":
            receiver = self.user_manager.get_user(receiver_phone)
            if not receiver:
                return False, "Receiver not found in the system."
            if receiver.phone == owner.phone:
                return False, "You cannot schedule a payment to yourself."
            if receiver.currency != owner.currency:
                return False, "Currency mismatch with receiver."
        else:  # BILL_PAYMENT
            if not biller_name or not biller_id:
                return False, "Biller name and biller ID are required."

        first_run = start_at or utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO scheduled_payments
                (owner_phone, type, receiver_phone, biller_name, biller_id, amount,
                 currency, description, frequency, next_run_at, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ''', (owner.phone, p_type, receiver_phone or None, biller_name or None,
                  biller_id or None, str(amount_decimal), owner.currency,
                  description, frequency, first_run, utcnow().isoformat()))
            conn.commit()
        log_event(owner.phone, "SCHEDULED_PAYMENT_CREATED", target=owner.phone,
                  details=f"{p_type} {amount_decimal} {frequency}"
                          + (f" -> {receiver_phone}" if receiver_phone else f" -> {biller_name}"))
        return True, "Scheduled payment created."

    def list(self, owner_phone: str) -> List[Dict]:
        """All scheduled payments of the owner, soonest first."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scheduled_payments WHERE owner_phone = ? ORDER BY next_run_at",
                (owner_phone,))
            return [dict(r) for r in cursor.fetchall()]

    def get(self, sp_id: int) -> Optional[Dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM scheduled_payments WHERE id = ?", (sp_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def cancel(self, owner_phone: str, sp_id: int) -> Tuple[bool, str]:
        """Cancel (deactivate) a scheduled payment. The record is kept for history."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_payments SET active = 0, last_status = 'CANCELLED' WHERE id = ? AND owner_phone = ?",
                (sp_id, owner_phone))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Scheduled payment not found."
        log_event(owner_phone, "SCHEDULED_PAYMENT_CANCELLED", target=str(sp_id))
        return True, "Scheduled payment cancelled."

    def set_active(self, owner_phone: str, sp_id: int, active: bool) -> Tuple[bool, str]:
        """Pause (active=False) or resume (active=True) a scheduled payment."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE scheduled_payments SET active = ? WHERE id = ? AND owner_phone = ?",
                (1 if active else 0, sp_id, owner_phone))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Scheduled payment not found."
        action = "resumed" if active else "paused"
        log_event(owner_phone, "SCHEDULED_PAYMENT_UPDATED", target=str(sp_id), details=action)
        return True, f"Scheduled payment {action}."

    def process_due(self, now=None) -> List[Dict]:
        """Execute every active scheduled payment whose next_run_at has passed.

        Rows are claimed (last_run_at stamped) inside the same connection before
        execution, so concurrent runs can never double-fire a payment.
        Returns a list of result dicts (id, ok, message).
        """
        now = now or utcnow()
        results = []
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM scheduled_payments WHERE active = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now.isoformat(),))
            due_rows = [dict(r) for r in cursor.fetchall()]
            for sp in due_rows:
                # Claim the row — only the claimer proceeds
                cursor.execute(
                    "UPDATE scheduled_payments SET last_run_at = ? WHERE id = ? AND active = 1",
                    (now.isoformat(), sp["id"]))
                if cursor.rowcount == 0:
                    continue
                conn.commit()

                if sp["type"] == "TRANSFER":
                    ok, msg = self.transaction_manager.transfer(
                        sp["owner_phone"], sp["receiver_phone"], float(sp["amount"]),
                        sp["description"] or "Scheduled transfer")
                else:
                    ok, msg = self.transaction_manager.pay_bill(
                        sp["owner_phone"], float(sp["amount"]),
                        sp["biller_name"], sp["biller_id"],
                        sp["description"] or "Scheduled bill payment")

                if ok:
                    next_run = _next_run(sp["frequency"], now)
                    new_active = 1 if next_run else 0
                    status = f"OK: {msg}"
                else:
                    # Failure policy: deactivate so it is not retried silently
                    next_run = sp["next_run_at"]
                    new_active = 0
                    status = f"FAILED: {msg}"

                with get_db() as conn2:
                    cursor2 = conn2.cursor()
                    cursor2.execute('''
                    UPDATE scheduled_payments
                    SET last_status = ?, next_run_at = ?, active = ?
                    WHERE id = ?
                    ''', (status, next_run or sp["next_run_at"], new_active, sp["id"]))
                    conn2.commit()

                log_event(sp["owner_phone"],
                          "SCHEDULED_PAYMENT_EXECUTED" if ok else "SCHEDULED_PAYMENT_FAILED",
                          target=str(sp["id"]),
                          details=f"{sp['type']} {sp['amount']}: {msg}",
                          status="SUCCESS" if ok else "FAILURE")
                results.append({"id": sp["id"], "ok": ok, "message": msg, "status": status})
        return results
