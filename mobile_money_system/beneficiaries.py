"""Saved beneficiaries (frequent recipients with nicknames).

Lets users save payees once and send money to them in one tap. Beneficiaries
are scoped per owner; a beneficiary may point at a phone that is not (yet)
registered — the UI flags whether the recipient is a known user.
"""

import builtins

if __package__:
    from .audit import log_event
    from .database import get_db, init_db
    from .models import utcnow
    from .users import UserManager
else:
    from audit import log_event  # type: ignore[no-redef]
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]
    from users import UserManager  # type: ignore[no-redef]


class BeneficiaryManager:
    def __init__(self, user_manager: UserManager):
        self.user_manager = user_manager
        init_db()  # Ensure schema exists (safe on fresh databases)

    def add(self, owner_phone: str, phone: str, nickname: str = "") -> tuple[bool, str]:
        """Save a beneficiary. Nickname defaults to the recipient's name or phone."""
        if not self.user_manager.validate_phone(phone):
            return False, "Invalid international phone number format (use +countrycode...)"
        phone_e164 = self.user_manager.format_phone(phone)
        if phone_e164 == owner_phone:
            return False, "You cannot save yourself as a beneficiary."

        recipient = self.user_manager.get_user(phone_e164)
        nickname = (nickname or "").strip() or (recipient.name if recipient else phone_e164)

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM beneficiaries WHERE owner_phone = ? AND phone = ?",
                (owner_phone, phone_e164))
            if cursor.fetchone():
                # Already saved — just refresh the nickname
                cursor.execute(
                    "UPDATE beneficiaries SET nickname = ? WHERE owner_phone = ? AND phone = ?",
                    (nickname, owner_phone, phone_e164))
                conn.commit()
                return True, f"Beneficiary '{nickname}' updated."
            cursor.execute('''
            INSERT INTO beneficiaries (owner_phone, phone, nickname, created_at)
            VALUES (?, ?, ?, ?)
            ''', (owner_phone, phone_e164, nickname, utcnow().isoformat()))
            conn.commit()
        log_event(owner_phone, "BENEFICIARY_ADDED", target=phone_e164, details=f"nickname={nickname}")
        return True, f"Beneficiary '{nickname}' saved."

    def list(self, owner_phone: str) -> list[dict]:
        """All beneficiaries of the owner, most recently used first."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM beneficiaries WHERE owner_phone = ? ORDER BY last_used_at DESC, created_at DESC",
                (owner_phone,))
            rows = [dict(r) for r in cursor.fetchall()]
        for row in rows:
            recipient = self.user_manager.get_user(row["phone"])
            row["is_registered"] = recipient is not None
            row["recipient_name"] = recipient.name if recipient else ""
        return rows

    def get(self, owner_phone: str, phone: str) -> dict | None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM beneficiaries WHERE owner_phone = ? AND phone = ?",
                (owner_phone, phone))
            row = cursor.fetchone()
            return dict(row) if row else None

    def remove(self, owner_phone: str, phone: str) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM beneficiaries WHERE owner_phone = ? AND phone = ?",
                (owner_phone, phone))
            changed = cursor.rowcount
            conn.commit()
        if changed:
            log_event(owner_phone, "BENEFICIARY_REMOVED", target=phone)
        return changed > 0

    def rename(self, owner_phone: str, phone: str, nickname: str) -> tuple[bool, str]:
        nickname = (nickname or "").strip()
        if not nickname:
            return False, "Nickname cannot be empty."
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE beneficiaries SET nickname = ? WHERE owner_phone = ? AND phone = ?",
                (nickname, owner_phone, phone))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Beneficiary not found."
        return True, f"Beneficiary renamed to '{nickname}'."

    def touch(self, owner_phone: str, phone: str) -> None:
        """Record that a transfer was made to this beneficiary."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE beneficiaries SET last_used_at = ? WHERE owner_phone = ? AND phone = ?",
                (utcnow().isoformat(), owner_phone, phone))
            conn.commit()

    def recent_recipients(self, owner_phone: str, limit: int = 5) -> builtins.list[str]:
        """Phones the owner recently sent money to (from transaction history)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT receiver_phone, MAX(timestamp) AS last_tx
            FROM transactions
            WHERE sender_phone = ? AND type = 'TRANSFER' AND status = 'COMPLETED'
            GROUP BY receiver_phone
            ORDER BY last_tx DESC
            LIMIT ?
            ''', (owner_phone, limit))
            return [row["receiver_phone"] for row in cursor.fetchall()]
