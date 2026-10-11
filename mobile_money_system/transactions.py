import sqlite3
import time
import uuid
from datetime import timedelta
from decimal import Decimal

if __package__:
    from .audit import log_event
    from .config import get_decimal, get_int
    from .database import get_db, init_db, write_transaction
    from .events import EventDispatcher
    from .ledger import LedgerManager
    from .models import Transaction, utcnow
    from .users import UserManager
else:
    from audit import log_event  # type: ignore[no-redef]
    from config import get_decimal, get_int  # type: ignore[no-redef]
    from database import get_db, init_db, write_transaction  # type: ignore[no-redef]
    from events import EventDispatcher  # type: ignore[no-redef]
    from ledger import LedgerManager  # type: ignore[no-redef]
    from models import Transaction, utcnow  # type: ignore[no-redef]
    from users import UserManager  # type: ignore[no-redef]

# --- Universal pricing: the platform is free to use --------------------------
# There is no paid tier — every user gets the same rates and limits.
TRANSFER_FEE_RATE = Decimal("0.00")     # 0% P2P transfer fee
WITHDRAWAL_FEE_RATE = Decimal("0.005")  # 0.5% withdrawal fee
BILL_FEE = Decimal("0.25")              # flat $0.25 per bill payment

# Per-transaction limits by risk tier, with the universal 10x multiplier
RISK_TIER_LIMITS = {
    "low": Decimal("1000"),
    "standard": Decimal("5000"),
    "high": Decimal("50000"),
}
DEFAULT_LIMIT = Decimal("5000")
LIMIT_MULTIPLIER = 10  # every user gets 10x their risk-tier limit


class TransactionManager:
    def __init__(self, user_manager: UserManager, db_file: str = "transactions.json", ledger_file: str = "ledger.json"):
        self.user_manager = user_manager
        self.ledger = LedgerManager()
        init_db()  # Ensure schema exists (safe on fresh databases)
        # Integration hook: callables invoked as listener(event, txn.to_dict())
        # after every successful money movement. Delivery happens on a
        # background thread (EventDispatcher), so a slow webhook or SMTP send
        # never delays a payment — and a broken listener never breaks a
        # transaction.
        self.event_listeners: list = []
        self.dispatcher = EventDispatcher(self.event_listeners)

        # Configuration Limits (None currently active)

    def _emit(self, event: str, txn: Transaction) -> None:
        """Notify integrations (webhooks, notifications) of a transaction event.

        Delivery is asynchronous — this never blocks or fails the transaction.
        """
        if not self.event_listeners:
            return
        self.dispatcher.emit(event, txn.to_dict())

    def _alert_aml(self, txn: Transaction, flag_reason: str) -> None:
        """Auto-open a high-priority admin ticket when AML flags a transaction.

        Alerting must never break the transaction itself.
        """
        try:
            if __package__:
                from .tickets import TicketManager
            else:
                from tickets import TicketManager  # type: ignore[no-redef]
            TicketManager().create(
                "SYSTEM",
                f"AML flag: {txn.type} {txn.amount}",
                "security",
                f"Transaction {txn.id} was flagged ({flag_reason}). "
                f"From {txn.sender_phone} to {txn.receiver_phone}, "
                f"amount {txn.currency} {txn.amount}. Please review.",
                priority="high",
            )
        except Exception:
            pass

    # --- Atomic money movement -------------------------------------------
    # Every balance change runs inside ONE SQLite write transaction
    # (BEGIN IMMEDIATE): the balance is re-read and re-checked under the
    # write lock, and the transaction record, the ledger entries and the new
    # balance are written together — committing or rolling back as a unit.
    # Two concurrent transfers can never both spend the same money
    # (no double-spend), and a crash mid-transfer leaves no partial state.

    @staticmethod
    def _make_txn(sender: str, receiver: str, amount: Decimal, t_type: str, description: str = "", currency: str = "USD", flagged: bool = False, flag_reason: str = "", status: str = "COMPLETED") -> Transaction:
        """Build a Transaction object (no database write)."""
        # Generate a standard reference number (e.g., TXN-12345678-ABCD)
        timestamp_part = int(time.time())
        random_part = str(uuid.uuid4())[:8].upper()
        t_id = f"TXN-{timestamp_part}-{random_part}"

        return Transaction(
            id=t_id,
            sender_phone=sender,
            receiver_phone=receiver,
            amount=amount,
            currency=currency,
            type=t_type,
            description=description,
            timestamp=utcnow().isoformat(),
            status=status,
            flagged=flagged,
            flag_reason=flag_reason
        )

    @staticmethod
    def _insert_txn(cur, t: Transaction) -> None:
        cur.execute('''
        INSERT INTO transactions (id, sender_phone, receiver_phone, amount, currency, type, timestamp, description, status, flagged, flag_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (t.id, t.sender_phone, t.receiver_phone, str(t.amount), t.currency, t.type, t.timestamp, t.description, t.status, 1 if t.flagged else 0, t.flag_reason))

    @staticmethod
    def _insert_ledger_entries(cur, entries) -> None:
        for e in entries:
            cur.execute('''
            INSERT INTO ledger (id, transaction_id, account_id, amount, timestamp, description)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (e.id, e.transaction_id, e.account_id, str(e.amount), e.timestamp, e.description))

    @staticmethod
    def _get_balance(cur, phone: str) -> Decimal | None:
        """Read a user's balance inside the current write transaction."""
        row = cur.execute("SELECT balance FROM users WHERE phone = ?", (phone,)).fetchone()
        return Decimal(row["balance"]) if row else None

    @staticmethod
    def _set_balance(cur, phone: str, balance: Decimal) -> None:
        cur.execute("UPDATE users SET balance = ? WHERE phone = ?", (str(balance), phone))

    @staticmethod
    def _entries_balanced(entries) -> bool:
        """Double-entry invariant: every posted batch must sum to zero."""
        return sum((e.amount for e in entries), Decimal("0.0")) == Decimal("0.0")

    @staticmethod
    def _fee_config() -> tuple[Decimal, Decimal, Decimal]:
        """Operator pricing from app_settings (defaults keep the platform free:
        0% transfer, 0.5% withdrawal, $0.25 flat per bill)."""
        return (
            get_decimal("transfer_fee_rate"),
            get_decimal("withdrawal_fee_rate"),
            get_decimal("bill_fee_flat"),
        )

    def _create_transaction_record(self, sender: str, receiver: str, amount: Decimal, t_type: str, description: str = "", currency: str = "USD", flagged: bool = False, flag_reason: str = "", status: str = "COMPLETED") -> Transaction:
        t = self._make_txn(sender, receiver, amount, t_type, description=description,
                           currency=currency, flagged=flagged, flag_reason=flag_reason,
                           status=status)
        with get_db() as conn:
            self._insert_txn(conn.cursor(), t)
            conn.commit()
        return t

    def get_transaction(self, t_id: str) -> Transaction | None:
        with get_db() as conn:
            conn.row_factory = sqlite3.Row # Ensure rows can be accessed by name
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE id = ?", (t_id,))
            row = cursor.fetchone()
            if row:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                return Transaction.from_dict(t_dict)
        return None

    def admin_adjust_balance(self, phone: str, amount: float, reason: str, is_credit: bool = True) -> tuple[bool, str]:
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"

        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount"

        t_type = "ADMIN_CREDIT" if is_credit else "ADMIN_DEBIT"

        # Build the record + a balanced double-entry ledger batch up front
        txn = self._make_txn(
            sender="ADMIN",
            receiver=phone,
            amount=abs(amount_decimal),
            t_type=t_type,
            description=reason,
            currency=user.currency
        )
        if is_credit:
            entries = [
                self.ledger.create_entry(txn.id, "SYSTEM_CASH", -abs(amount_decimal), "Admin Cash In"),
                self.ledger.create_entry(txn.id, phone, abs(amount_decimal), "Admin Credit"),
            ]
        else:
            entries = [
                self.ledger.create_entry(txn.id, phone, -abs(amount_decimal), "Admin Debit"),
                self.ledger.create_entry(txn.id, "SYSTEM_CASH", abs(amount_decimal), "Admin Cash Out"),
            ]
        if not self._entries_balanced(entries):
            return False, "Transaction failed: Ledger imbalance."

        # Atomic: re-check + record + ledger + balance update in one transaction
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                balance = self._get_balance(cur, phone)
                if balance is None:
                    return False, "User not found"
                new_balance = balance + amount_decimal if is_credit else balance - amount_decimal
                if not is_credit and new_balance < 0:
                    return False, "Insufficient funds"
                self._insert_txn(cur, txn)
                self._insert_ledger_entries(cur, entries)
                self._set_balance(cur, phone, new_balance)
        except sqlite3.Error as e:
            return False, f"Transaction failed: {e}"

        user.balance = new_balance
        log_event("ADMIN", t_type, target=txn.id,
                  details=f"{t_type} of {amount_decimal} for {phone}. Reason: {reason}")
        return True, "Balance adjusted successfully."

    def reverse_transaction(self, transaction_id: str) -> tuple[bool, str]:
        # Find original
        txn = self.get_transaction(transaction_id)
        if not txn:
            return False, "Transaction not found"

        if txn.type == "REVERSAL":
            return False, "Cannot reverse a reversal"

        # Reverse Logic based on types
        if txn.type in ["TRANSFER", "PAYMENT", "BILL_PAY"]:
             # Atomic: re-read both balances under the write lock, apply the
             # reversal, post the reversal ledger batch, flag the original —
             # all in one transaction.
             rev = self._make_txn(
                 sender=txn.receiver_phone,
                 receiver=txn.sender_phone,
                 amount=txn.amount,
                 t_type="REVERSAL",
                 description=f"Reversal of {txn.id}",
                 currency=txn.currency
             )
             entries = [
                 self.ledger.create_entry(rev.id, txn.sender_phone, txn.amount, "Reversal Credit"),
                 self.ledger.create_entry(rev.id, txn.receiver_phone, -txn.amount, "Reversal Debit"),
             ]
             if not self._entries_balanced(entries):
                 return False, "Reversal failed: Ledger imbalance."

             try:
                 with write_transaction() as conn:
                     cur = conn.cursor()
                     sender_balance = self._get_balance(cur, txn.sender_phone)
                     if sender_balance is None:
                         return False, "Sender account missing"
                     # Credit Sender
                     self._set_balance(cur, txn.sender_phone, sender_balance + txn.amount)

                     # Debit Receiver if internal User (receiver might be external, e.g. BILL_PAY)
                     receiver_balance = self._get_balance(cur, txn.receiver_phone)
                     if receiver_balance is not None:
                         self._set_balance(cur, txn.receiver_phone, receiver_balance - txn.amount)

                     # Log Reversal
                     self._insert_txn(cur, rev)
                     self._insert_ledger_entries(cur, entries)
                     cur.execute("UPDATE transactions SET flagged = 1, flag_reason = flag_reason || ' [REVERSED]' WHERE id = ?", (transaction_id,))
             except sqlite3.Error as e:
                 return False, f"Reversal failed: {e}"

             return True, "Transaction reversed."

        return False, f"Reversal not implemented for type {txn.type}"

    def _check_limits(self, phone: str, amount: Decimal) -> tuple[bool, str]:
        # 1. KYC Check
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"

        if user.status != "active":
            return False, f"Account is {user.status}"

        if not user.is_verified:
            # Maybe allow small deposits? strict: block all.
            return False, "Transaction blocked: KYC Not Verified."

        # Per-transaction limit: risk-tier base with the universal 10x multiplier
        limit = RISK_TIER_LIMITS.get(user.risk_tier, DEFAULT_LIMIT) * LIMIT_MULTIPLIER

        if amount > limit:
            return False, f"Amount exceeds per-transaction limit (${limit})"

        return True, ""

    def _assess_aml(self, phone: str, amount: Decimal) -> tuple[bool, str]:
        flagged = False
        reason = []

        # Thresholds are operator-configurable (admin Security tab)
        large_threshold = get_decimal("aml_large_amount_threshold")
        velocity_count = get_int("aml_velocity_count", 5)
        velocity_window_minutes = get_int("aml_velocity_window_minutes", 5)

        # 1. Large Transaction
        if amount >= large_threshold:
            flagged = True
            reason.append(f"Large amount (>={large_threshold})")

        # 2. Velocity Check (Rapid Movement)
        now = utcnow()
        time_window = (now - timedelta(minutes=velocity_window_minutes)).isoformat()

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE sender_phone = ? AND timestamp > ?", (phone, time_window))
            count = cursor.fetchone()[0]

        if count >= velocity_count:
            flagged = True
            reason.append("Rapid movement (Velocity)")

        return flagged, "; ".join(reason)

    def deposit(self, phone: str, amount: float, description: str = "Deposit") -> tuple[bool, str]:
        amount_decimal = Decimal(str(amount))
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount_decimal <= 0:
            return False, "Invalid amount"

        # Check Limits & KYC
        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
             return False, msg

        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # Build the record + a balanced double-entry batch (sums to zero)
        txn = self._make_txn(
            sender="SYSTEM",
            receiver=phone,
            amount=amount_decimal,
            t_type="DEPOSIT",
            description=description,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries = [
            self.ledger.create_entry(txn.id, "SYSTEM_CASH", -amount_decimal, "Cash In"),
            self.ledger.create_entry(txn.id, phone, amount_decimal, "Deposit to Wallet")
        ]
        if not self._entries_balanced(entries):
            return False, "Transaction failed: Ledger imbalance."

        # Atomic: record + ledger + balance credit in one write transaction
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                balance = self._get_balance(cur, phone)
                if balance is None:
                    return False, "User not found"
                self._insert_txn(cur, txn)
                self._insert_ledger_entries(cur, entries)
                self._set_balance(cur, phone, balance + amount_decimal)
        except sqlite3.Error as e:
            return False, f"Transaction failed: {e}"

        user.balance += amount_decimal
        log_event(phone, "DEPOSIT", target=txn.id, details=f"Deposited {amount_decimal}")
        if flagged:
            self._alert_aml(txn, flag_reason)
        self._emit("DEPOSIT", txn)
        return True, f"Deposited {amount_decimal} successfully."

    def withdraw(self, phone: str, amount: float, description: str = "Withdrawal") -> tuple[bool, str]:
        amount_decimal = Decimal(str(amount))
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        if amount_decimal <= 0:
            return False, "Invalid amount"

        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
            log_event(phone, "WITHDRAWAL", target=phone, details=f"Blocked: {msg}", status="BLOCKED")
            return False, msg

        _transfer_fee, withdrawal_fee_rate, _bill_fee = self._fee_config()
        fee = amount_decimal * withdrawal_fee_rate
        total_deduction = amount_decimal + fee

        if user.balance < total_deduction:
            return False, "Insufficient balance."

        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # 1. Main Withdrawal
        txn_wd = self._make_txn(
            sender=phone,
            receiver="SYSTEM",
            amount=amount_decimal,
            t_type="WITHDRAWAL",
            description=description,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries_wd = [
            self.ledger.create_entry(txn_wd.id, phone, -amount_decimal, "Withdrawal from Wallet"),
            self.ledger.create_entry(txn_wd.id, "SYSTEM_CASH", amount_decimal, "Cash Out")
        ]

        # 2. Fee (no fee records are created when the fee is zero)
        entries_fee = []
        txn_fee = None
        if fee > 0:
            txn_fee = self._make_txn(
                sender=phone,
                receiver="SYSTEM_REVENUE",
                amount=fee,
                t_type="FEE",
                description=f"Fee: {description}",
                currency=user.currency
            )
            entries_fee = [
                self.ledger.create_entry(txn_fee.id, phone, -fee, "Withdrawal Fee"),
                self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
            ]

        all_entries = entries_wd + entries_fee
        if not self._entries_balanced(all_entries):
            return False, "Transaction failed: Ledger imbalance."

        # Atomic: re-check funds under the write lock, then record + ledger +
        # balance debit in one transaction
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                balance = self._get_balance(cur, phone)
                if balance is None:
                    return False, "User not found"
                if balance < total_deduction:
                    return False, "Insufficient balance."
                self._insert_txn(cur, txn_wd)
                if txn_fee is not None:
                    self._insert_txn(cur, txn_fee)
                self._insert_ledger_entries(cur, all_entries)
                self._set_balance(cur, phone, balance - total_deduction)
        except sqlite3.Error as e:
            return False, f"Transaction failed: {e}"

        user.balance -= total_deduction
        log_event(phone, "WITHDRAWAL", target=txn_wd.id,
                  details=f"Withdrew {amount_decimal} (fee {fee})")
        if flagged:
            self._alert_aml(txn_wd, flag_reason)
        self._emit("WITHDRAWAL", txn_wd)
        return True, f"Withdrawn ${amount_decimal}."

    def transfer(self, sender_phone: str, receiver_phone: str, amount: float, description: str = "Transfer") -> tuple[bool, str]:
        """Transfer money between two users. Returns (success, message)."""
        ok, msg, _txn = self._transfer(sender_phone, receiver_phone, amount, description)
        return ok, msg

    def transfer_with_ref(self, sender_phone: str, receiver_phone: str, amount: float, description: str = "Transfer") -> tuple[bool, str, Transaction | None]:
        """transfer() that also returns the created transaction record
        (used by the API to include a reference in idempotent responses)."""
        return self._transfer(sender_phone, receiver_phone, amount, description)

    def _transfer(self, sender_phone: str, receiver_phone: str, amount: float, description: str = "Transfer") -> tuple[bool, str, Transaction | None]:
        sender = self.user_manager.get_user(sender_phone)
        receiver = self.user_manager.get_user(receiver_phone)

        if not sender:
            return False, "Sender not found", None
        if not receiver:
            return False, "Receiver not found", None
        if sender_phone == receiver_phone:
            return False, "Cannot transfer to self", None
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount", None

        # Currency check
        if sender.currency != receiver.currency:
            return False, "Currency mismatch.", None

        allowed, msg = self._check_limits(sender_phone, amount_decimal)
        if not allowed:
            log_event(sender_phone, "TRANSFER", target=receiver_phone,
                      details=f"Blocked: {msg} ({amount_decimal})", status="BLOCKED")
            return False, msg, None

        transfer_fee_rate, _withdrawal_fee, _bill_fee = self._fee_config()
        fee = amount_decimal * transfer_fee_rate
        total_deduction = amount_decimal + fee

        if sender.balance < total_deduction:
            return False, "Insufficient balance.", None

        # AML Check
        flagged, flag_reason = self._assess_aml(sender_phone, amount_decimal)

        # 1. Transfer
        txn_tr = self._make_txn(
            sender=sender_phone,
            receiver=receiver_phone,
            amount=amount_decimal,
            t_type="TRANSFER",
            description=description,
            currency=sender.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries_tr = [
            self.ledger.create_entry(txn_tr.id, sender_phone, -amount_decimal, "Transfer Out"),
            self.ledger.create_entry(txn_tr.id, receiver_phone, amount_decimal, "Transfer In")
        ]

        # 2. Fee (no fee records are created when the fee is zero)
        entries_fee = []
        txn_fee = None
        if fee > 0:
            txn_fee = self._make_txn(
                sender=sender_phone,
                receiver="SYSTEM_REVENUE",
                amount=fee,
                t_type="FEE",
                description="Fee for Transfer",
                currency=sender.currency
            )
            entries_fee = [
                self.ledger.create_entry(txn_fee.id, sender_phone, -fee, "Transfer Fee"),
                self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
            ]

        all_entries = entries_tr + entries_fee
        if not self._entries_balanced(all_entries):
            return False, "Transaction failed: Ledger imbalance.", None

        # Atomic: re-read both balances under the write lock, re-check the
        # sender's funds, then record + ledger + both balance updates in one
        # transaction — two racing transfers can never both spend the same
        # money.
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                sender_balance = self._get_balance(cur, sender_phone)
                receiver_balance = self._get_balance(cur, receiver_phone)
                if sender_balance is None or receiver_balance is None:
                    return (False, "Sender not found", None) if sender_balance is None else (False, "Receiver not found", None)
                if sender_balance < total_deduction:
                    return False, "Insufficient balance.", None
                self._insert_txn(cur, txn_tr)
                if txn_fee is not None:
                    self._insert_txn(cur, txn_fee)
                self._insert_ledger_entries(cur, all_entries)
                self._set_balance(cur, sender_phone, sender_balance - total_deduction)
                self._set_balance(cur, receiver_phone, receiver_balance + amount_decimal)
        except sqlite3.Error as e:
            return False, f"Transaction failed: {e}", None

        sender.balance -= total_deduction
        receiver.balance += amount_decimal
        log_event(sender_phone, "TRANSFER", target=txn_tr.id,
                  details=f"{amount_decimal} -> {receiver_phone} (fee {fee})"
                  + (f" - {description}" if description else "")
                  + (" [AML FLAGGED: " + flag_reason + "]" if flagged else ""),
                  status="SUCCESS")
        if flagged:
            self._alert_aml(txn_tr, flag_reason)
        self._emit("TRANSFER", txn_tr)
        return True, "Transfer successful", txn_tr

    def pay_bill(self, phone: str, amount: float, biller_name: str, biller_id: str, description: str = "Bill Payment") -> tuple[bool, str]:
        user = self.user_manager.get_user(phone)
        if not user:
            return False, "User not found"
        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
           return False, "Invalid amount"

        allowed, msg = self._check_limits(phone, amount_decimal)
        if not allowed:
            log_event(phone, "BILL_PAYMENT", target=biller_id, details=f"Blocked: {msg}", status="BLOCKED")
            return False, msg

        _transfer_fee, _withdrawal_fee, bill_fee = self._fee_config()
        fee = bill_fee
        total_deduction = amount_decimal + fee

        if user.balance < total_deduction:
             return False, "Insufficient balance."

        # AML Check
        flagged, flag_reason = self._assess_aml(phone, amount_decimal)

        # 1. Bill Payment
        full_desc = f"{biller_name} ({biller_id}) - {description}"
        txn_bill = self._make_txn(
            sender=phone,
            receiver="BILLER_SYSTEM",
            amount=amount_decimal,
            t_type="BILL_PAYMENT",
            description=full_desc,
            currency=user.currency,
            flagged=flagged,
            flag_reason=flag_reason
        )
        entries_bill = [
            self.ledger.create_entry(txn_bill.id, phone, -amount_decimal, "Bill Payment"),
            self.ledger.create_entry(txn_bill.id, "BILLER_SYSTEM", amount_decimal, "Bill Payment Received")
        ]

        # 2. Fee
        entries_fee = []
        txn_fee = None
        if fee > 0:
            txn_fee = self._make_txn(
                sender=phone,
                receiver="SYSTEM_REVENUE",
                amount=fee,
                t_type="FEE",
                description=f"Fee: {biller_name}",
                currency=user.currency
            )
            entries_fee = [
                self.ledger.create_entry(txn_fee.id, phone, -fee, "Bill Fee"),
                self.ledger.create_entry(txn_fee.id, "SYSTEM_REVENUE", fee, "Fee Revenue")
            ]

        all_entries = entries_bill + entries_fee
        if not self._entries_balanced(all_entries):
            return False, "Transaction failed: Ledger imbalance."

        # Atomic: re-check funds under the write lock, then record + ledger +
        # balance debit in one transaction
        try:
            with write_transaction() as conn:
                cur = conn.cursor()
                balance = self._get_balance(cur, phone)
                if balance is None:
                    return False, "User not found"
                if balance < total_deduction:
                    return False, "Insufficient balance."
                self._insert_txn(cur, txn_bill)
                if txn_fee is not None:
                    self._insert_txn(cur, txn_fee)
                self._insert_ledger_entries(cur, all_entries)
                self._set_balance(cur, phone, balance - total_deduction)
        except sqlite3.Error as e:
            return False, f"Transaction failed: {e}"

        user.balance -= total_deduction
        log_event(phone, "BILL_PAYMENT", target=txn_bill.id,
                  details=f"{biller_name} {amount_decimal} (fee {fee})")
        if flagged:
            self._alert_aml(txn_bill, flag_reason)
        self._emit("BILL_PAYMENT", txn_bill)
        return True, f"Paid {biller_name} successfully."

    def request_money(self, requester_phone: str, payer_phone: str, amount: float, description: str = "Money Request") -> tuple[bool, str]:
        # Just create a record with PENDING status. No money moves yet.
        requester = self.user_manager.get_user(requester_phone)
        payer = self.user_manager.get_user(payer_phone)

        if not requester or not payer:
            return False, "User not found"

        amount_decimal = Decimal(str(amount))
        if amount_decimal <= 0:
            return False, "Invalid amount"

        t = self._create_transaction_record(
            sender=payer_phone, # Payer will be the sender eventually
            receiver=requester_phone,
            amount=amount_decimal,
            t_type="REQUEST",
            description=description,
            currency=requester.currency, # Use requester's currency preference?? Or payer's? Usually Payer pays in their currency.
            # But the request is FOR an amount.
            # Let's assume requester wants their currency.
            status="PENDING"
        )
        self._emit("REQUEST", t)
        return True, "Request sent successfully."

    def process_request(self, t_id: str, action: str) -> tuple[bool, str]: # action = 'PAY' or 'DECLINE'
        # Find transaction
        target_t = self.get_transaction(t_id)
        if not target_t:
            return False, "Request not found"

        if target_t.type != "REQUEST" or target_t.status != "PENDING":
            return False, "Invalid request status"

        if action == "DECLINE":
            with get_db() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE transactions SET status = 'DECLINED' WHERE id = ?", (t_id,))
                conn.commit()
            log_event(target_t.sender_phone, "REQUEST_DECLINED", target=t_id,
                      details=f"Declined request of {target_t.amount} from {target_t.receiver_phone}")
            return True, "Request declined."

        elif action == "PAY":
            # Execute Transfer Logic
            success, msg = self.transfer(target_t.sender_phone, target_t.receiver_phone, float(target_t.amount), target_t.description)
            if success:
                with get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE transactions SET status = 'COMPLETED' WHERE id = ?", (t_id,))
                    conn.commit()
                log_event(target_t.sender_phone, "REQUEST_PAID", target=t_id,
                          details=f"Paid request of {target_t.amount} to {target_t.receiver_phone}")
                return True, "Request paid successfully."
            else:
                return False, msg

        return False, "Invalid action"

    def get_history(self, phone: str) -> list[Transaction]:
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions WHERE sender_phone = ? OR receiver_phone = ? ORDER BY timestamp DESC", (phone, phone))
            rows = cursor.fetchall()
            txns = []
            for row in rows:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                txns.append(Transaction.from_dict(t_dict))
            return txns

    @property
    def transactions(self) -> list[Transaction]:
        # Legacy compatibility for parts that iterate over all txns
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions")
            rows = cursor.fetchall()
            txns = []
            for row in rows:
                t_dict = dict(row)
                t_dict['flagged'] = bool(t_dict['flagged'])
                txns.append(Transaction.from_dict(t_dict))
            return txns
