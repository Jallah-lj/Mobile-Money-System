"""Data retention: prune old rows according to configurable retention periods.

Retention periods are operator settings (app_settings, in days; 0 = keep
forever). The audit trail keeps the default of 365 days; short-lived security
state (OTPs, rate-limit hits) is pruned after a day. Runs on demand from the
admin System tab, and can be wired to the background scheduler.
"""

import time
from datetime import timedelta

try:
    from config import get_int, set_setting
    from database import get_db, init_db
    from models import utcnow
except ImportError:
    from mobile_money_system.config import get_int, set_setting
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.models import utcnow


class RetentionManager:
    # table -> (timestamp column, setting key, column kind)
    #   kind "iso"  = ISO-8601 text timestamps (naive UTC)
    #   kind "real" = unix epoch seconds (float)
    TABLES = {
        "audit_log": ("timestamp", "retention_days_audit_log", "iso"),
        "sessions": ("last_seen", "retention_days_sessions", "iso"),
        "webhook_deliveries": ("delivered_at", "retention_days_webhook_deliveries", "iso"),
        "login_attempts": ("at", "retention_days_login_attempts", "real"),
        "otp_codes": ("expires_at", "retention_days_misc", "real"),
        "rate_limit_hits": ("at", "retention_days_misc", "real"),
        "idempotency_keys": ("created_at", "retention_days_idempotency_keys", "iso"),
        "account_lockouts": ("locked_until", "retention_days_account_lockouts", "real"),
    }

    def __init__(self):
        init_db()

    def run_retention(self, now=None) -> dict:
        """Delete rows older than their retention period.

        Returns {table: rows_deleted} and stamps retention_last_run.
        """
        now = now or utcnow()
        deleted: dict[str, int] = {}
        with get_db() as conn:
            cursor = conn.cursor()
            for table, (column, setting_key, kind) in self.TABLES.items():
                days = get_int(setting_key, 0)
                if days <= 0:
                    continue  # retention disabled for this table
                if kind == "real":
                    cutoff = time.time() - days * 86400
                    cursor.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
                else:
                    cutoff = (now - timedelta(days=days)).isoformat()
                    if table == "webhook_deliveries":
                        # delivered_at is NULL for pending/failed deliveries
                        cursor.execute(
                            f"DELETE FROM {table} WHERE {column} IS NOT NULL AND {column} < ?",
                            (cutoff,))
                    else:
                        cursor.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
                deleted[table] = cursor.rowcount
            conn.commit()
        set_setting("retention_last_run", now.isoformat())
        return deleted
