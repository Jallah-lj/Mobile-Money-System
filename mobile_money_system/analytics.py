"""Personal analytics & account statements.

Pure functions over a user's transaction list — no database access, so they
are trivial to unit-test. All money values are Decimal; timestamps are the
naive-UTC ISO strings stored in the transactions table (string-comparable).
"""

import calendar
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

try:
    from models import Transaction, utcnow
except ImportError:
    from mobile_money_system.models import Transaction, utcnow

# Types that credit the receiver / debit the sender
CREDIT_TYPES = ("TRANSFER", "DEPOSIT", "ADMIN_CREDIT", "REVERSAL")
DEBIT_TYPES = ("TRANSFER", "WITHDRAWAL", "BILL_PAYMENT", "ADMIN_DEBIT")

CATEGORY_LABELS = {
    "TRANSFER": "P2P Transfers",
    "WITHDRAWAL": "Withdrawals",
    "BILL_PAYMENT": "Bill Payments",
    "FEE": "Fees",
    "ADMIN_DEBIT": "Adjustments",
}


def month_bounds(year: int, month: int) -> Tuple[str, str]:
    """ISO bounds [start, end) of a calendar month (naive UTC)."""
    start = f"{year:04d}-{month:02d}-01T00:00:00"
    if month == 12:
        end = f"{year + 1:04d}-01-01T00:00:00"
    else:
        end = f"{year:04d}-{month + 1:02d}-01T00:00:00"
    return start, end


def in_month(timestamp: str, year: int, month: int) -> bool:
    start, end = month_bounds(year, month)
    return start <= timestamp < end


def net_flow(t: Transaction, phone: str) -> Decimal:
    """Signed effect of a transaction on the user's balance (0 if unrelated)."""
    amount = Decimal(str(t.amount))
    if t.type == "FEE":
        return -amount if t.sender_phone == phone else Decimal("0")
    if t.receiver_phone == phone and t.type in CREDIT_TYPES:
        return amount
    if t.sender_phone == phone and t.type in DEBIT_TYPES:
        return -amount
    return Decimal("0")


def monthly_totals(txns: List[Transaction], phone: str, months: int = 6,
                   now=None) -> List[Dict]:
    """Income / spending / fees per month for the last `months` months.

    Returns a chronological list of {month, income, spending, fees} dicts
    (Decimal values), oldest first, ending at the current month.
    """
    now = now or utcnow()
    result = []
    for i in range(months - 1, -1, -1):
        # Walk back `i` months from the current month
        y, m = now.year, now.month - i
        while m <= 0:
            y -= 1
            m += 12
        start, end = month_bounds(y, m)
        income = spending = fees = Decimal("0")
        for t in txns:
            if not (start <= t.timestamp < end):
                continue
            flow = net_flow(t, phone)
            if t.type == "FEE" and t.sender_phone == phone:
                fees += Decimal(str(t.amount))
            elif flow > 0:
                income += flow
            elif flow < 0:
                spending += -flow
        result.append({
            "month": f"{y:04d}-{m:02d}",
            "income": income,
            "spending": spending,
            "fees": fees,
        })
    return result


def spending_by_category(txns: List[Transaction], phone: str,
                         year: Optional[int] = None,
                         month: Optional[int] = None) -> Dict[str, Decimal]:
    """Outgoing spend grouped by category (optionally for one month)."""
    categories: Dict[str, Decimal] = {}
    for t in txns:
        if year is not None and month is not None and not in_month(t.timestamp, year, month):
            continue
        if t.sender_phone != phone:
            continue
        if t.type not in CATEGORY_LABELS:
            continue
        label = CATEGORY_LABELS[t.type]
        categories[label] = categories.get(label, Decimal("0")) + Decimal(str(t.amount))
    return categories


def top_counterparties(txns: List[Transaction], phone: str, n: int = 5) -> List[Dict]:
    """Top recipients of the user's outgoing transfers (all time)."""
    grouped: Dict[str, Dict] = {}
    for t in txns:
        if t.sender_phone != phone or t.type != "TRANSFER" or t.status != "COMPLETED":
            continue
        entry = grouped.setdefault(t.receiver_phone, {"phone": t.receiver_phone,
                                                     "amount": Decimal("0"), "count": 0})
        entry["amount"] += Decimal(str(t.amount))
        entry["count"] += 1
    ranked = sorted(grouped.values(), key=lambda e: e["amount"], reverse=True)
    return ranked[:n]


def monthly_statement(txns: List[Transaction], phone: str,
                      year: int, month: int) -> Dict:
    """Full monthly statement: opening/closing balances, flows, transactions.

    Opening balance is reconstructed from all flows before the month; the
    closing balance equals opening + income - spending - fees (and, when the
    transaction history is complete, the user's actual current balance).
    """
    start, end = month_bounds(year, month)
    opening = Decimal("0")
    income = spending = fees = Decimal("0")
    month_txns = []
    for t in sorted(txns, key=lambda x: x.timestamp):
        flow = net_flow(t, phone)
        if t.timestamp < start:
            opening += flow
            continue
        if t.timestamp >= end:
            continue
        month_txns.append(t)
        if t.type == "FEE" and t.sender_phone == phone:
            fees += Decimal(str(t.amount))
        elif flow > 0:
            income += flow
        elif flow < 0:
            spending += -flow
    closing = opening + income - spending - fees
    return {
        "year": year,
        "month": month,
        "opening_balance": opening,
        "closing_balance": closing,
        "income": income,
        "spending": spending,
        "fees": fees,
        "tx_count": len(month_txns),
        "transactions": month_txns,
    }


def budget_status(txns: List[Transaction], phone: str, budget: Decimal,
                  year: int, month: int) -> Dict:
    """Spending (incl. fees) against a monthly budget."""
    cats = spending_by_category(txns, phone, year, month)
    spent = sum(cats.values(), Decimal("0"))
    budget = Decimal(str(budget))
    remaining = budget - spent
    pct = (float(spent / budget) * 100) if budget > 0 else None
    return {
        "budget": budget,
        "spent": spent,
        "remaining": remaining,
        "pct": pct,
    }
