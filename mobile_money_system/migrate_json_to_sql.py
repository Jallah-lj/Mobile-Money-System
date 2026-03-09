import json
import os
import sqlite3
from decimal import Decimal
from database import DB_PATH, init_db

def migrate():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Migrate Users
    if os.path.exists("users.json"):
        with open("users.json", "r") as f:
            users_data = json.load(f)
            for phone, u in users_data.items():
                cursor.execute('''
                INSERT OR REPLACE INTO users (phone, name, pin, balance, currency, role, sec_q, sec_a, id_type, id_number, is_verified, status, risk_tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    u.get("phone", phone),
                    u.get("name"),
                    u.get("pin"),
                    u.get("balance", "0.0"),
                    u.get("currency", "USD"),
                    u.get("role", "user"),
                    u.get("sec_q", ""),
                    u.get("sec_a", ""),
                    u.get("id_type", ""),
                    u.get("id_number", ""),
                    1 if u.get("is_verified") else 0,
                    u.get("status", "active"),
                    u.get("risk_tier", "standard")
                ))
        print("Migrated Users.")

    # 2. Migrate Transactions
    if os.path.exists("transactions.json"):
        with open("transactions.json", "r") as f:
            txns_data = json.load(f)
            for t in txns_data:
                cursor.execute('''
                INSERT OR REPLACE INTO transactions (id, sender_phone, receiver_phone, amount, currency, type, timestamp, description, status, flagged, flag_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    t.get("id"),
                    t.get("sender_phone"),
                    t.get("receiver_phone"),
                    t.get("amount"),
                    t.get("currency", "USD"),
                    t.get("type"),
                    t.get("timestamp"),
                    t.get("description", ""),
                    t.get("status", "COMPLETED"),
                    1 if t.get("flagged") else 0,
                    t.get("flag_reason", "")
                ))
        print("Migrated Transactions.")

    # 3. Migrate Ledger
    if os.path.exists("ledger.json"):
        with open("ledger.json", "r") as f:
            ledger_data = json.load(f)
            for l in ledger_data:
                cursor.execute('''
                INSERT OR REPLACE INTO ledger (id, transaction_id, account_id, amount, timestamp, description)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    l.get("id"),
                    l.get("transaction_id"),
                    l.get("account_id"),
                    l.get("amount"),
                    l.get("timestamp"),
                    l.get("description", "")
                ))
        print("Migrated Ledger.")

    conn.commit()
    conn.close()
    print("Migration finished successfully.")

if __name__ == "__main__":
    migrate()
