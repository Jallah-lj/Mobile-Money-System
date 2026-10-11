"""Registered billers (utility providers) for bill payments.

Admins manage the list from the Bills & Revenue tab; users pick a saved
biller on the Pay Bills page instead of typing provider details by hand.
"""

if __package__:
    from .database import get_db, init_db
    from .models import utcnow
else:
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]

CATEGORIES = ("Airtime & Data", "Electricity (Prepaid)", "Water Utility",
              "Internet Subscription", "Government", "Other")


class BillerManager:
    def __init__(self):
        init_db()

    def add(self, name: str, category: str, biller_id: str, fee_note: str = "") -> tuple[bool, str]:
        name = (name or "").strip()
        biller_id = (biller_id or "").strip()
        if not name or not biller_id:
            return False, "Name and biller ID are required"
        with get_db() as conn:
            conn.execute(
                "INSERT INTO billers (name, category, biller_id, fee_note, active, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (name, category, biller_id, fee_note, utcnow().isoformat()))
            conn.commit()
        return True, f"Biller '{name}' added"

    def remove(self, biller_id: int) -> tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.execute("DELETE FROM billers WHERE id = ?", (biller_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return False, "Biller not found"
        return True, "Biller removed"

    def deactivate(self, biller_id: int) -> tuple[bool, str]:
        with get_db() as conn:
            cursor = conn.execute(
                "UPDATE billers SET active = 0 WHERE id = ?", (biller_id,))
            conn.commit()
            if cursor.rowcount == 0:
                return False, "Biller not found"
        return True, "Biller deactivated"

    def list(self, active_only: bool = True) -> list[dict]:
        with get_db() as conn:
            if active_only:
                rows = conn.execute(
                    "SELECT * FROM billers WHERE active = 1 ORDER BY name").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM billers ORDER BY active DESC, name").fetchall()
            return [dict(r) for r in rows]
