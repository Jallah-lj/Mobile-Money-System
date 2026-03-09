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
        
        conn.commit()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
