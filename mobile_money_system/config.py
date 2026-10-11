"""Operator configuration, persisted in the app_settings table.

Settings survive restarts and are shared across processes. Every key has a
built-in default, so a fresh database always behaves like the documented
configuration. Universal pricing defaults keep the platform free to use.
"""

import sqlite3
from decimal import Decimal, InvalidOperation

if __package__:
    from .database import get_db, init_db
    from .models import utcnow
else:
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]

# Built-in defaults — used when a key has never been stored.
DEFAULTS = {
    # Universal pricing (the platform is free to use by default)
    "transfer_fee_rate": "0.00",       # 0% P2P transfer fee
    "withdrawal_fee_rate": "0.005",    # 0.5% withdrawal fee
    "bill_fee_flat": "0.25",           # flat $0.25 per bill payment
    # AML thresholds
    "aml_large_amount_threshold": "10000",
    "aml_velocity_count": "5",
    "aml_velocity_window_minutes": "5",
    # Retention periods (days; 0 = keep forever)
    "retention_days_audit_log": "365",
    "retention_days_sessions": "30",
    "retention_days_webhook_deliveries": "90",
    "retention_days_login_attempts": "90",
    "retention_days_misc": "1",        # otp_codes, rate_limit_hits
    "retention_days_idempotency_keys": "30",
    "retention_days_account_lockouts": "7",
    # Backups
    "auto_backup_hours": "24",
}


def get_setting(key: str, default: str | None = None) -> str:
    """Read a setting; falls back to the built-in default, then `default`."""
    fallback = DEFAULTS.get(key, default if default is not None else "")
    try:
        with get_db() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else fallback
    except sqlite3.OperationalError:
        # Fresh database without schema yet
        init_db()
        return fallback


def set_setting(key: str, value: str) -> None:
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, str(value), utcnow().isoformat()))
        conn.commit()


def reset_setting(key: str) -> None:
    """Remove an override so the built-in default applies again."""
    with get_db() as conn:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        conn.commit()


def all_settings() -> dict:
    """Merged view: built-in defaults overlaid with stored overrides."""
    merged = dict(DEFAULTS)
    try:
        with get_db() as conn:
            for row in conn.execute("SELECT key, value FROM app_settings"):
                merged[row["key"]] = row["value"]
    except sqlite3.OperationalError:
        init_db()
    return merged


def get_decimal(key: str, default: str | None = None) -> Decimal:
    try:
        return Decimal(get_setting(key, default))
    except (InvalidOperation, TypeError):
        return Decimal(DEFAULTS.get(key, default or "0"))


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key))
    except (ValueError, TypeError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key))
    except (ValueError, TypeError):
        return default
