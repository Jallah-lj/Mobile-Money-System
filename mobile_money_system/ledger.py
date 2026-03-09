import uuid
import time
from decimal import Decimal
from typing import List, Dict, Optional
from datetime import datetime, timezone

try:
    from models import LedgerEntry
    from database import get_db
except ImportError:
    from mobile_money_system.models import LedgerEntry
    from mobile_money_system.database import get_db

class LedgerManager:
    """
    Manages double-entry bookkeeping.
    Ensures that for every transaction, the sum of all entries is ZERO.
    """
    def __init__(self, ledger_file: str = "ledger.json"):
        # We no longer use ledger_file, everything in main SQLite
        pass

    def post_entries(self, entries: List[LedgerEntry]) -> bool:
        """
        Validates and posts a batch of entries.
        The sum of amounts in the batch MUST be zero.
        """
        total = sum((e.amount for e in entries), Decimal("0.0"))
        
        if total != Decimal("0.0"):
            print(f"Ledger Error: Unbalanced transaction. Sum: {total}")
            return False
            
        with get_db() as conn:
            cursor = conn.cursor()
            for e in entries:
                cursor.execute('''
                INSERT INTO ledger (id, transaction_id, account_id, amount, timestamp, description)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (e.id, e.transaction_id, e.account_id, str(e.amount), e.timestamp, e.description))
            conn.commit()
        return True

    def create_entry(self, transaction_id: str, account_id: str, amount: Decimal, description: str = "") -> LedgerEntry:
        timestamp_part = int(time.time())
        random_part = str(uuid.uuid4())[:8].upper()
        entry_id = f"LEG-{timestamp_part}-{random_part}"
        
        return LedgerEntry(
            id=entry_id,
            transaction_id=transaction_id,
            account_id=account_id,
            amount=amount,
            timestamp=datetime.now(timezone.utc).isoformat(),
            description=description
        )

    def get_account_balance(self, account_id: str) -> Decimal:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT amount FROM ledger WHERE account_id = ?", (account_id,))
            rows = cursor.fetchall()
            balance = sum((Decimal(row['amount']) for row in rows), Decimal("0.0"))
            return balance

