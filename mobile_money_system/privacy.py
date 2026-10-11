"""Privacy & data controls (GDPR-style).

Two capabilities:

* **Data export** — a user can download everything the platform holds about
  them (profile, transactions, beneficiaries, scheduled payments, tickets,
  notification channels, sessions) as JSON or CSV.
* **Account deletion** — a user requests deletion; an admin reviews and
  approves/rejects. On approval the account row is removed and the user's
  phone number is **pseudonymized** in retained financial records (audit and
  transaction history must survive for compliance, but no longer identify the
  person). Beneficiaries, scheduled payments, tickets, notification channels
  and sessions are deleted outright.

Every action is audit-logged.
"""

import hashlib

try:
    from audit import log_event
    from database import get_db, init_db
    from models import utcnow
except ImportError:
    from mobile_money_system.audit import log_event
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.models import utcnow

DELETION_STATUSES = ("pending", "approved", "rejected")


def pseudonymize(phone: str) -> str:
    """Stable, non-reversible placeholder for a deleted user's phone number."""
    return "DELETED-" + hashlib.sha256(phone.encode()).hexdigest()[:12]


class PrivacyManager:
    def __init__(self):
        init_db()  # Ensure schema exists (safe on fresh databases)

    # --- Data export ---

    def export_user_data(self, phone: str) -> dict | None:
        """Everything the platform holds about the user, as a plain dict."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (phone,))
            user_row = cursor.fetchone()
            if not user_row:
                return None
            data: dict = {"exported_at": utcnow().isoformat(), "profile": dict(user_row)}
            # Never export credentials
            data["profile"].pop("pin", None)
            data["profile"].pop("sec_a", None)

            def fetch_all(table, where, params):
                cursor.execute(f"SELECT * FROM {table} WHERE {where}", params)
                return [dict(r) for r in cursor.fetchall()]

            data["transactions"] = fetch_all(
                "transactions", "sender_phone = ? OR receiver_phone = ?", (phone, phone))
            data["beneficiaries"] = fetch_all("beneficiaries", "owner_phone = ?", (phone,))
            data["scheduled_payments"] = fetch_all("scheduled_payments", "owner_phone = ?", (phone,))
            data["tickets"] = fetch_all("tickets", "phone = ?", (phone,))
            data["notification_channels"] = fetch_all(
                "notification_channels", "phone = ?", (phone,))
            data["sessions"] = fetch_all("sessions", "phone = ?", (phone,))
            data["audit_trail"] = fetch_all("audit_log", "actor_phone = ?", (phone,))
            return data

    # --- Deletion requests ---

    def request_deletion(self, phone: str, reason: str = "") -> tuple[bool, str]:
        """User asks to delete their account. Requires admin approval."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone FROM users WHERE phone = ?", (phone,))
            if not cursor.fetchone():
                return False, "User not found"
            cursor.execute(
                "SELECT id FROM account_deletions WHERE phone = ? AND status = 'pending'", (phone,))
            if cursor.fetchone():
                return False, "A deletion request is already pending."
            cursor.execute('''
            INSERT INTO account_deletions (phone, reason, status, requested_at)
            VALUES (?, ?, 'pending', ?)
            ''', (phone, reason, utcnow().isoformat()))
            req_id = cursor.lastrowid
            conn.commit()
        log_event(phone, "DELETION_REQUESTED", target=str(req_id), details=reason[:200])
        return True, f"Deletion request #{req_id} submitted. An admin will review it."

    def pending_deletions(self) -> list[dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM account_deletions WHERE status = 'pending' ORDER BY requested_at")
            return [dict(r) for r in cursor.fetchall()]

    def get_request(self, request_id: int) -> dict | None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM account_deletions WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def reject_deletion(self, request_id: int, admin_phone: str, note: str = "") -> tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE account_deletions
            SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_note = ?
            WHERE id = ? AND status = 'pending'
            ''', (admin_phone, utcnow().isoformat(), note, request_id))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Request not found or already reviewed."
        req = self.get_request(request_id)
        log_event(admin_phone, "DELETION_REJECTED", target=str(request_id),
                  details=f"for {req['phone'] if req else '?'}: {note[:200]}")
        return True, "Deletion request rejected. The account stays active."

    def approve_deletion(self, request_id: int, admin_phone: str) -> tuple[bool, str]:
        """Approve a deletion: remove the account, pseudonymize financial records."""
        req = self.get_request(request_id)
        if not req or req["status"] != "pending":
            return False, "Request not found or already reviewed."
        phone = req["phone"]
        pseudo = pseudonymize(phone)
        now = utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            # 1. Pseudonymize retained financial/compliance records
            cursor.execute(
                "UPDATE transactions SET sender_phone = ? WHERE sender_phone = ?", (pseudo, phone))
            cursor.execute(
                "UPDATE transactions SET receiver_phone = ? WHERE receiver_phone = ?", (pseudo, phone))
            cursor.execute(
                "UPDATE audit_log SET actor_phone = ? WHERE actor_phone = ?", (pseudo, phone))
            cursor.execute(
                "UPDATE ledger SET account_id = ? WHERE account_id = ?", (pseudo, phone))
            # 2. Delete personal data outright
            for table, col in (("users", "phone"), ("beneficiaries", "owner_phone"),
                               ("scheduled_payments", "owner_phone"), ("tickets", "phone"),
                               ("notification_channels", "phone"), ("sessions", "phone")):
                cursor.execute(f"DELETE FROM {table} WHERE {col} = ?", (phone,))
            # 3. Close the request
            cursor.execute('''
            UPDATE account_deletions
            SET status = 'approved', reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            ''', (admin_phone, now, request_id))
            conn.commit()
        log_event(admin_phone, "DELETION_APPROVED", target=phone,
                  details=f"Account deleted; records pseudonymized as {pseudo}")
        return True, f"Account {phone} deleted. Financial records were pseudonymized ({pseudo})."

    def cancel_deletion_request(self, phone: str, request_id: int) -> bool:
        """A user withdraws their own pending request."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM account_deletions WHERE id = ? AND phone = ? AND status = 'pending'",
                (request_id, phone))
            changed = cursor.rowcount
            conn.commit()
        return changed > 0

    def my_deletion_requests(self, phone: str) -> list[dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM account_deletions WHERE phone = ? ORDER BY requested_at DESC", (phone,))
            return [dict(r) for r in cursor.fetchall()]


def export_to_csv(data: dict) -> str:
    """Flatten the export into CSV sections (profile + transactions)."""
    import csv
    from io import StringIO
    buf = StringIO()
    buf.write("# PROFILE\n")
    writer = csv.DictWriter(buf, fieldnames=list(data["profile"].keys()))
    writer.writeheader()
    writer.writerow(data["profile"])
    for section in ("transactions", "beneficiaries", "scheduled_payments", "tickets"):
        buf.write(f"\n# {section.upper()}\n")
        rows = data.get(section) or []
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return buf.getvalue()
