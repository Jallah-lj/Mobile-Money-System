import os
import sqlite3
from contextlib import contextmanager, suppress

# The SQLite file location can be overridden (e.g. a Docker volume mount).
DB_PATH = os.environ.get("MMS_DB_PATH", "mobile_money.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    # Wait for the write lock instead of failing immediately when another
    # connection (thread/process) is mid-write.
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def write_transaction():
    """A single serialized write transaction: BEGIN IMMEDIATE ... COMMIT.

    BEGIN IMMEDIATE takes the database write lock up front, so a
    read-check-write sequence inside this block is atomic — two concurrent
    transfers can never both spend the same balance (no double-spend).
    Rolls back on any exception.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        conn.commit()
    finally:
        conn.close()

def _table_columns(cursor, table: str):
    cursor.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cursor.fetchall()}

def _add_column(cursor, table: str, column: str, definition: str):
    """Add a column to a table if it does not exist yet (idempotent migration)."""
    if column not in _table_columns(cursor, table):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()

        # Write-Ahead Logging: readers never block the writer and vice versa,
        # which is what makes concurrent balance updates safe. (Persisted in
        # the database file; falls back silently on filesystems without WAL.)
        with suppress(sqlite3.Error):
            cursor.execute("PRAGMA journal_mode=WAL")

        # Users Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            pin TEXT NOT NULL,
            balance TEXT DEFAULT '0.0',
            currency TEXT DEFAULT 'USD',
            role TEXT DEFAULT 'user',
            sec_q TEXT,
            sec_a TEXT,
            id_type TEXT,
            id_number TEXT,
            is_verified INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            risk_tier TEXT DEFAULT 'standard'
        )
        ''')

        # Transactions Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            sender_phone TEXT,
            receiver_phone TEXT,
            amount TEXT NOT NULL,
            currency TEXT NOT NULL,
            type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'COMPLETED',
            flagged INTEGER DEFAULT 0,
            flag_reason TEXT
        )
        ''')

        # Ledger Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS ledger (
            id TEXT PRIMARY KEY,
            transaction_id TEXT,
            account_id TEXT,
            amount TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            description TEXT,
            FOREIGN KEY (transaction_id) REFERENCES transactions (id)
        )
        ''')

        # Audit Log Table (append-only security trail)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            actor_phone TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            details TEXT,
            status TEXT DEFAULT 'SUCCESS'
        )
        ''')

        # Sessions Table (active login sessions — revocable, auditable)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            phone TEXT NOT NULL,
            provider TEXT DEFAULT 'web',
            user_agent TEXT,
            ip TEXT,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
        ''')

        # Beneficiaries Table (saved recipients with nicknames)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS beneficiaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_phone TEXT NOT NULL,
            phone TEXT NOT NULL,
            nickname TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            UNIQUE(owner_phone, phone)
        )
        ''')

        # Scheduled Payments Table (one-off future payments & standing orders)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_phone TEXT NOT NULL,
            type TEXT NOT NULL,
            receiver_phone TEXT,
            biller_name TEXT,
            biller_id TEXT,
            amount TEXT NOT NULL,
            currency TEXT DEFAULT 'USD',
            description TEXT,
            frequency TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            last_run_at TEXT,
            last_status TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        ''')

        # Webhooks Table (outbound event subscriptions for integrations)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            secret TEXT NOT NULL,
            events TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        ''')

        # Webhook Deliveries Table (delivery log: attempts, status, errors)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            payload TEXT NOT NULL,
            status_code INTEGER,
            attempts INTEGER DEFAULT 0,
            delivered_at TEXT,
            error TEXT
        )
        ''')

        # Notification Channels Table (per-user SMS/email destinations)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            channel TEXT NOT NULL,
            destination TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
        ''')

        # Support Tickets Table (user issues -> admin queue)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            subject TEXT NOT NULL,
            category TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            priority TEXT DEFAULT 'normal',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            admin_reply TEXT,
            replied_at TEXT,
            replied_by TEXT
        )
        ''')

        # Account Deletion Requests (GDPR-style: user request -> admin approval)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_deletions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT
        )
        ''')

        # OTP Codes (replaces the old in-memory dict — survives restarts and is
        # shared across processes; only a hash of the code is stored)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS otp_codes (
            phone TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL,
            expires_at REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        ''')

        # Login Attempts (brute-force tracking, DB-backed)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            at REAL NOT NULL
        )
        ''')

        # Account Lockouts (DB-backed: survive restarts, shared across workers)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS account_lockouts (
            phone TEXT PRIMARY KEY,
            locked_until REAL NOT NULL
        )
        ''')

        # Rate Limit Hits (DB-backed sliding window, shared across processes)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS rate_limit_hits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            at REAL NOT NULL
        )
        ''')

        # Idempotency Keys (API: replay-safe duplicate POSTs)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        ''')

        # App Settings (operator configuration: fees, AML thresholds, retention)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        ''')

        # Backups Registry (snapshot metadata for the admin backup tool)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            note TEXT
        )
        ''')

        # --- Indexes for the hot query paths ---
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_transactions_sender ON transactions(sender_phone)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_receiver ON transactions(receiver_phone)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_phone)",
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_phone ON sessions(phone)",
            "CREATE INDEX IF NOT EXISTS idx_ledger_account ON ledger(account_id)",
            "CREATE INDEX IF NOT EXISTS idx_ledger_transaction ON ledger(transaction_id)",
            "CREATE INDEX IF NOT EXISTS idx_beneficiaries_owner ON beneficiaries(owner_phone)",
            "CREATE INDEX IF NOT EXISTS idx_scheduled_owner ON scheduled_payments(owner_phone)",
            "CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_payments(next_run_at)",
            "CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)",
            "CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON webhook_deliveries(webhook_id)",
            "CREATE INDEX IF NOT EXISTS idx_deletions_phone ON account_deletions(phone)",
            "CREATE INDEX IF NOT EXISTS idx_notif_channels_phone ON notification_channels(phone)",
            "CREATE INDEX IF NOT EXISTS idx_login_attempts_phone ON login_attempts(phone)",
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_key ON rate_limit_hits(key)",
        ]
        for _sql in indexes:
            cursor.execute(_sql)

        # --- Schema migrations for existing databases ---
        _add_column(cursor, "users", "two_factor_enabled", "INTEGER DEFAULT 1")
        _add_column(cursor, "users", "monthly_budget", "TEXT DEFAULT '0'")

        conn.commit()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
