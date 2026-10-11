"""Login session management.

Every successful web login creates a server-side session row (token, owner,
device metadata, activity timestamps). Sessions can be listed and revoked
per-device ("log out everywhere"), and a revoked session immediately ends
the login on the next app run — closing the "stolen browser tab" gap that a
purely client-side logout leaves open.
"""

import uuid

try:
    from database import get_db, init_db
    from models import utcnow
except ImportError:
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.models import utcnow


class SessionManager:
    def __init__(self):
        init_db()  # Ensure schema exists (safe on fresh databases)

    def create_session(self, phone: str, provider: str = "web",
                       user_agent: str = "", ip: str = "") -> str:
        """Create a new session and return its opaque token."""
        token = uuid.uuid4().hex
        now = utcnow().isoformat()
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO sessions (token, phone, provider, user_agent, ip, created_at, last_seen, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ''', (token, phone, provider, user_agent, ip, now, now))
            conn.commit()
        return token

    def get_session(self, token: str) -> dict | None:
        """Return the session row, or None if the token is unknown."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE token = ?", (token,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def is_session_valid(self, token: str, phone: str) -> bool:
        """A session is valid when it exists, is active, and belongs to the phone."""
        sess = self.get_session(token)
        return bool(sess and sess["active"] and sess["phone"] == phone)

    def touch(self, token: str) -> None:
        """Update last_seen (called on every app run while the session is live)."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET last_seen = ? WHERE token = ? AND active = 1",
                           (utcnow().isoformat(), token))
            conn.commit()

    def revoke(self, token: str) -> bool:
        """Revoke a single session. Returns True when a row was deactivated."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE sessions SET active = 0 WHERE token = ? AND active = 1", (token,))
            changed = cursor.rowcount
            conn.commit()
            return changed > 0

    def revoke_all(self, phone: str, except_token: str | None = None) -> int:
        """Revoke every active session of the user (optionally keeping one)."""
        with get_db() as conn:
            cursor = conn.cursor()
            if except_token:
                cursor.execute(
                    "UPDATE sessions SET active = 0 WHERE phone = ? AND active = 1 AND token != ?",
                    (phone, except_token))
            else:
                cursor.execute(
                    "UPDATE sessions SET active = 0 WHERE phone = ? AND active = 1", (phone,))
            changed = cursor.rowcount
            conn.commit()
            return changed

    def list_active(self, phone: str) -> list[dict]:
        """All active sessions for a user, most recently seen first."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE phone = ? AND active = 1 ORDER BY last_seen DESC",
                (phone,))
            return [dict(row) for row in cursor.fetchall()]

    def end_session(self, token: str) -> None:
        """Convenience alias for revoke (semantic at call sites)."""
        self.revoke(token)
