"""Professionalism: data retention — prune old rows, keep recent ones."""

import time
from datetime import timedelta

from mobile_money_system.config import get_setting, set_setting
from mobile_money_system.database import get_db
from mobile_money_system.models import utcnow
from mobile_money_system.retention import RetentionManager


def test_retention_prunes_old_rows_only(managers):
    rm = RetentionManager()
    old_iso = (utcnow() - timedelta(days=400)).isoformat()
    new_iso = utcnow().isoformat()
    old_real = time.time() - 400 * 86400
    now_real = time.time()

    with get_db() as conn:
        conn.execute("INSERT INTO audit_log (id, timestamp, actor_phone, action) VALUES ('ret-a1', ?, 'ret-actor', 'OLD')", (old_iso,))
        conn.execute("INSERT INTO audit_log (id, timestamp, actor_phone, action) VALUES ('ret-a2', ?, 'ret-actor', 'NEW')", (new_iso,))
        conn.execute("INSERT INTO otp_codes (phone, code_hash, expires_at, created_at) VALUES ('ret-p1', 'h', ?, ?)", (old_real, new_iso))
        conn.execute("INSERT INTO rate_limit_hits (key, at) VALUES ('ret-old', ?)", (old_real,))
        conn.execute("INSERT INTO rate_limit_hits (key, at) VALUES ('ret-new', ?)", (now_real,))
        conn.commit()

    deleted = rm.run_retention()
    assert deleted["audit_log"] == 1
    assert deleted["otp_codes"] == 1
    assert deleted["rate_limit_hits"] == 1

    with get_db() as conn:
        # Only the NEW audit row for our actor remains
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE actor_phone = 'ret-actor'").fetchone()[0]
        assert n == 1
        assert conn.execute("SELECT COUNT(*) FROM otp_codes").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rate_limit_hits WHERE key = 'ret-new'").fetchone()[0] == 1

    assert get_setting("retention_last_run", "") != ""


def test_retention_zero_days_keeps_everything(managers):
    set_setting("retention_days_audit_log", "0")
    old_iso = (utcnow() - timedelta(days=400)).isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO audit_log (id, timestamp, actor_phone, action) VALUES ('ret-keep', ?, 'ret-actor', 'OLD')", (old_iso,))
        conn.commit()
    deleted = RetentionManager().run_retention()
    assert deleted.get("audit_log", 0) == 0
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE id = 'ret-keep'").fetchone()[0]
    assert n == 1


def test_retention_respects_custom_period(managers):
    """A shorter retention period prunes rows the default would keep."""
    set_setting("retention_days_audit_log", "30")
    old_iso = (utcnow() - timedelta(days=60)).isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO audit_log (id, timestamp, actor_phone, action) VALUES ('ret-c1', ?, 'ret-actor', 'OLD')", (old_iso,))
        conn.commit()
    deleted = RetentionManager().run_retention()
    assert deleted["audit_log"] == 1
