"""Append-only audit logging for security-relevant system events.

Every login attempt, financial operation and administrative action is
recorded here. Entries are never updated or deleted by application
code — the log is a compliance trail.
"""

import uuid

try:
    from database import get_db
    from models import AuditEntry, utcnow
except ImportError:
    from mobile_money_system.database import get_db
    from mobile_money_system.models import AuditEntry, utcnow


def log_event(actor_phone: str, action: str, target: str = "",
              details: str = "", status: str = "SUCCESS") -> AuditEntry:
    """Record an audit event. Failures here must never break the main flow."""
    entry = AuditEntry(
        id=f"AUD-{int(utcnow().timestamp())}-{str(uuid.uuid4())[:8].upper()}",
        timestamp=utcnow().isoformat(),
        actor_phone=actor_phone or "SYSTEM",
        action=action,
        target=target,
        details=details,
        status=status
    )
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO audit_log (id, timestamp, actor_phone, action, target, details, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (entry.id, entry.timestamp, entry.actor_phone, entry.action,
                  entry.target, entry.details, entry.status))
            conn.commit()
    except Exception as e:
        # Auditing must never take down a transaction; surface to stderr instead.
        print(f"Audit log write failed: {e}")
    return entry


def get_audit_logs(limit: int = 200, actor_phone: str | None = None,
                   action: str | None = None) -> list[AuditEntry]:
    """Retrieve audit entries, newest first, with optional filters."""
    query = "SELECT * FROM audit_log"
    clauses: list[str] = []
    params: list = []  # mixes str filters and the int LIMIT
    if actor_phone:
        clauses.append("actor_phone = ?")
        params.append(actor_phone)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [AuditEntry.from_dict(dict(row)) for row in cursor.fetchall()]
