"""
Shared test infrastructure for the Mobile Money System test suite.

Usage in each test class:
    def setUp(self):
        from tests.conftest import setup_test_db, insert_user
        self._db_path, self._db_teardown = setup_test_db()
        insert_user("alice", "Alice", balance="500.0")

    def tearDown(self):
        self._db_teardown()
"""

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

# Module-level variable holds the current test DB path.
# Set by setup_test_db(), cleared by the teardown callback.
_current_db_path: str = ""


def _make_get_db(path: str):
    """Return a get_db context-manager factory bound to *path*."""
    @contextmanager
    def get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()
    return get_db


def _init_schema(path: str) -> None:
    """Create all required tables in a fresh database file."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            phone           TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            pin             TEXT NOT NULL,
            balance         TEXT DEFAULT '0.0',
            currency        TEXT DEFAULT 'USD',
            role            TEXT DEFAULT 'user',
            sec_q           TEXT,
            sec_a           TEXT,
            id_type         TEXT,
            id_number       TEXT,
            is_verified     INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'active',
            risk_tier       TEXT DEFAULT 'standard',
            failed_attempts INTEGER DEFAULT 0,
            locked_until    TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id              TEXT PRIMARY KEY,
            sender_phone    TEXT,
            receiver_phone  TEXT,
            amount          TEXT NOT NULL,
            currency        TEXT NOT NULL,
            type            TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            description     TEXT,
            status          TEXT DEFAULT 'COMPLETED',
            flagged         INTEGER DEFAULT 0,
            flag_reason     TEXT
        );

        CREATE TABLE IF NOT EXISTS ledger (
            id              TEXT PRIMARY KEY,
            transaction_id  TEXT,
            account_id      TEXT,
            amount          TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            description     TEXT,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id)
        );
    """)
    conn.close()


def setup_test_db():
    """
    Create a fresh temporary SQLite database, patch get_db in all relevant
    modules, and return ``(db_path, teardown_fn)``.

    Call ``teardown_fn()`` in ``tearDown()`` to stop patches and remove the
    temporary file.
    """
    global _current_db_path

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _current_db_path = path

    _init_schema(path)
    get_db = _make_get_db(path)

    patches = [
        patch("mobile_money_system.transactions.get_db", get_db),
        patch("mobile_money_system.users.get_db", get_db),
        patch("mobile_money_system.ledger.get_db", get_db),
        patch("mobile_money_system.database.get_db", get_db),
    ]
    for p in patches:
        p.start()

    def teardown():
        global _current_db_path
        for p in patches:
            try:
                p.stop()
            except RuntimeError:
                pass
        _current_db_path = ""
        try:
            os.unlink(path)
        except OSError:
            pass

    return path, teardown


def get_test_conn() -> sqlite3.Connection:
    """Open a connection to the current test database."""
    assert _current_db_path, (
        "No test database is active. Call setup_test_db() in setUp() first."
    )
    conn = sqlite3.connect(_current_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def insert_user(phone: str, name: str, balance: str = "0.0",
                currency: str = "USD", is_verified: bool = True,
                risk_tier: str = "standard", status: str = "active") -> None:
    """Insert a test user into the current test database."""
    import bcrypt
    hashed = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    conn = get_test_conn()
    conn.execute(
        """INSERT OR REPLACE INTO users
           (phone, name, pin, balance, currency, is_verified, risk_tier, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (phone, name, hashed, balance, currency,
         1 if is_verified else 0, risk_tier, status)
    )
    conn.commit()
    conn.close()


def get_balance(phone: str) -> "Decimal":
    """Read a user's current balance from the current test database."""
    from decimal import Decimal
    conn = get_test_conn()
    row = conn.execute("SELECT balance FROM users WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return Decimal(row[0]) if row else Decimal("0.0")
