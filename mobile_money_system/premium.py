"""Premium membership tier engine.

Defines the benefits of the Premium tier and exposes pure helper functions
that the transaction layer, API, CLI and web UI all share, so the fee
schedule is consistent across every surface.

Premium perks:
  * 0% P2P transfer fees        (free tier: 1%)
  * 50% off withdrawal fees     (free tier: 1% -> premium: 0.5%)
  * 50% off bill payment fees   (free tier: $0.50 -> premium: $0.25)
  * 10x per-transaction limit   (free tier: $5,000 -> premium: $50,000,
                                  scaled by risk tier as before)
  * Loyalty points on spend     (1 point per $10 transacted)
  * 500 points = 1 free month of Premium
"""

from decimal import Decimal
from typing import Optional

try:
    from models import User, utcnow
except ImportError:
    from mobile_money_system.models import User, utcnow

# --- Tier configuration -----------------------------------------------------

TIER_FREE = "free"
TIER_PREMIUM = "premium"

PREMIUM_MONTHLY_FEE = Decimal("4.99")   # Subscription price per 30 days
PREMIUM_PERIOD_DAYS = 30                # Length of one subscription period

# Loyalty program
POINTS_PER_SPEND_UNIT = Decimal("10")  # 1 point per $10 of transaction amount
POINTS_FOR_FREE_MONTH = 500             # Redemption cost for 1 free month

# Fee schedule (rates as Decimal fractions of the amount)
FREE_TRANSFER_FEE_RATE = Decimal("0.01")     # 1%
PREMIUM_TRANSFER_FEE_RATE = Decimal("0.00")  # 0%

FREE_WITHDRAWAL_FEE_RATE = Decimal("0.01")     # 1%
PREMIUM_WITHDRAWAL_FEE_RATE = Decimal("0.005") # 0.5%

FREE_BILL_FEE = Decimal("0.50")     # Flat fee
PREMIUM_BILL_FEE = Decimal("0.25")  # Flat fee

# Per-transaction limits by risk tier (free tier)
RISK_TIER_LIMITS = {
    "low": Decimal("1000"),
    "standard": Decimal("5000"),
    "high": Decimal("50000"),
}
DEFAULT_LIMIT = Decimal("5000")
PREMIUM_LIMIT_MULTIPLIER = 10  # Premium multiplies the risk-tier limit


# --- Tier helpers -----------------------------------------------------------

def is_premium_user(user: Optional[User]) -> bool:
    """True if the user currently holds an active Premium subscription.

    A subscription whose expiry has passed is treated as lapsed: the tier
    stays 'premium' in the record (history) but the perks are inactive.
    """
    if not user or user.tier != TIER_PREMIUM:
        return False
    if not user.premium_expires:
        return False
    return user.premium_expires > utcnow().isoformat()


def transfer_fee_rate(user: Optional[User]) -> Decimal:
    return PREMIUM_TRANSFER_FEE_RATE if is_premium_user(user) else FREE_TRANSFER_FEE_RATE


def withdrawal_fee_rate(user: Optional[User]) -> Decimal:
    return PREMIUM_WITHDRAWAL_FEE_RATE if is_premium_user(user) else FREE_WITHDRAWAL_FEE_RATE


def bill_fee(user: Optional[User]) -> Decimal:
    return PREMIUM_BILL_FEE if is_premium_user(user) else FREE_BILL_FEE


def transaction_limit(user: Optional[User]) -> Decimal:
    """Per-transaction amount limit for the user (risk tier x tier multiplier)."""
    if not user:
        return Decimal("0")
    base = RISK_TIER_LIMITS.get(user.risk_tier, DEFAULT_LIMIT)
    if is_premium_user(user):
        base = base * PREMIUM_LIMIT_MULTIPLIER
    return base


def points_earned_for(amount: Decimal) -> int:
    """Loyalty points earned for a transaction amount (1 point per $10)."""
    if amount <= 0:
        return 0
    return int(amount / POINTS_PER_SPEND_UNIT)


def fee_schedule(user: Optional[User]) -> dict:
    """Human/machine-readable summary of the user's current fee schedule."""
    premium = is_premium_user(user)
    return {
        "tier": TIER_PREMIUM if premium else TIER_FREE,
        "transfer_fee_rate": str(transfer_fee_rate(user)),
        "withdrawal_fee_rate": str(withdrawal_fee_rate(user)),
        "bill_fee": str(bill_fee(user)),
        "transaction_limit": str(transaction_limit(user)),
        "loyalty_points": user.loyalty_points if user else 0,
        "premium_expires": user.premium_expires if user else "",
        "premium_monthly_fee": str(PREMIUM_MONTHLY_FEE),
    }
