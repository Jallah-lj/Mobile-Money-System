"""Support ticketing — user issues with an admin queue and replies.

Replaces the old mock support console: users open tickets from the Support
tab; admins work the queue (filter, reply, change status) from the admin
Support tab. Every mutation is audit-logged.
"""


if __package__:
    from .audit import log_event
    from .database import get_db, init_db
    from .models import utcnow
else:
    from audit import log_event  # type: ignore[no-redef]
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]

TICKET_STATUSES = ("open", "in_progress", "resolved", "closed")
TICKET_CATEGORIES = ("payment", "account", "kyc", "security", "other")
TICKET_PRIORITIES = ("low", "normal", "high")


class TicketManager:
    def __init__(self):
        init_db()  # Ensure schema exists (safe on fresh databases)

    def create(self, phone: str, subject: str, category: str, message: str,
               priority: str = "normal") -> tuple[bool, str]:
        """Open a new support ticket. Returns (success, message)."""
        subject = (subject or "").strip()
        message = (message or "").strip()
        category = (category or "").strip().lower()
        priority = (priority or "normal").strip().lower()
        if not subject or not message:
            return False, "Subject and message are required."
        if category not in TICKET_CATEGORIES:
            return False, f"Category must be one of {TICKET_CATEGORIES}"
        if priority not in TICKET_PRIORITIES:
            return False, f"Priority must be one of {TICKET_PRIORITIES}"
        now = utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO tickets (phone, subject, category, message, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            ''', (phone, subject, category, message, priority, now, now))
            ticket_id = cursor.lastrowid
            conn.commit()
        log_event(phone, "TICKET_CREATED", target=str(ticket_id),
                  details=f"[{category}/{priority}] {subject}")
        return True, f"Ticket #{ticket_id} opened. Our team will reply soon."

    def get(self, ticket_id: int) -> dict | None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def my_tickets(self, phone: str) -> list[dict]:
        """A user's own tickets, newest first."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tickets WHERE phone = ? ORDER BY updated_at DESC", (phone,))
            return [dict(r) for r in cursor.fetchall()]

    def all_tickets(self, status: str | None = None,
                    category: str | None = None) -> list[dict]:
        """Admin queue, newest first, with optional filters."""
        query = "SELECT * FROM tickets"
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC"
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def reply(self, ticket_id: int, admin_phone: str, message: str) -> tuple[bool, str]:
        """Admin reply — visible to the user; moves the ticket to in_progress."""
        message = (message or "").strip()
        if not message:
            return False, "Reply cannot be empty."
        now = utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE tickets
            SET admin_reply = ?, replied_at = ?, replied_by = ?,
                status = CASE WHEN status = 'open' THEN 'in_progress' ELSE status END,
                updated_at = ?
            WHERE id = ?
            ''', (message, now, admin_phone, now, ticket_id))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Ticket not found."
        log_event(admin_phone, "TICKET_REPLIED", target=str(ticket_id), details=message[:200])
        return True, "Reply sent to the user."

    def set_status(self, ticket_id: int, status: str, actor_phone: str = "ADMIN") -> tuple[bool, str]:
        status = (status or "").strip().lower()
        if status not in TICKET_STATUSES:
            return False, f"Status must be one of {TICKET_STATUSES}"
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tickets SET status = ?, updated_at = ? WHERE id = ?",
                           (status, utcnow().isoformat(), ticket_id))
            changed = cursor.rowcount
            conn.commit()
        if not changed:
            return False, "Ticket not found."
        log_event(actor_phone, "TICKET_STATUS", target=str(ticket_id), details=status)
        return True, f"Ticket #{ticket_id} marked {status}."
