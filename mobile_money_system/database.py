import sqlite3
import os
from contextlib import contextmanager

DB_PATH = "mobile_money.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
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

        # --- Schema migrations for existing databases ---
        _add_column(cursor, "users", "two_factor_enabled", "INTEGER DEFAULT 1")
        _add_column(cursor, "users", "monthly_budget", "TEXT DEFAULT '0'")

        conn.commit()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
