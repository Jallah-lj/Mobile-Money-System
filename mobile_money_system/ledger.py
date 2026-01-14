import uuid
import time
from decimal import Decimal
from typing import List, Dict, Optional

try:
    from models import LedgerEntry
    from storage import JsonStorage
except ImportError:
    from mobile_money_system.models import LedgerEntry
    from mobile_money_system.storage import JsonStorage

class LedgerManager:
    """
    Manages double-entry bookkeeping.
    Ensures that for every transaction, the sum of all entries is ZERO.
    """
    def __init__(self, db_file: str = "ledger.json"):
        self.storage = JsonStorage(db_file)
        self.entries: List[LedgerEntry] = []
        self.load_entries()

    def load_entries(self):
        data = self.storage.load(default=[])
        if isinstance(data, list):
            self.entries = [LedgerEntry.from_dict(e) for e in data]
        else:
            self.entries = []

    def save_entries(self):
        data = [e.to_dict() for e in self.entries]
        self.storage.save(data)

    def post_entries(self, entries: List[LedgerEntry]) -> bool:
        """
        Validates and posts a batch of entries.
        The sum of amounts in the batch MUST be zero.
        """
        total = sum((e.amount for e in entries), Decimal("0.0"))
        
        # In double entry, Debits + Credits must equal 0 (if we treat Debits as negative and Credits as positive)
        # Or Debits = Credits.
        # Here we follow: + is Credit (Increase Liability/User Balance), - is Debit (Decrease Liability/User Balance).
        if total != Decimal("0.0"):
            print(f"Ledger Error: Unbalanced transaction. Sum: {total}")
            return False
            
        self.entries.extend(entries)
        self.save_entries()
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
            description=description
        )

    def get_account_balance(self, account_id: str) -> Decimal:
        """
        Calculates balance from the beginning of time.
        In a real system, we would use snapshots/checkpoints.
        """
        balance = Decimal("0.0")
        for entry in self.entries:
            if entry.account_id == account_id:
                balance += entry.amount
        return balance
