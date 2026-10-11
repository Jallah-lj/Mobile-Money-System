"""Standalone scheduler worker: runs due scheduled payments plus daily
maintenance (retention, auto-backup) without the Streamlit app.

Used by the docker-compose ``scheduler`` service, so standing orders fire on
time even when nobody has the app open. The in-app background scheduler
(scheduled.start_scheduler) covers single-process deployments.

Usage:  python -m mobile_money_system.scheduler_worker
Env:    MMS_DB_PATH               database location (default mobile_money.db)
        MMS_SCHEDULER_TICK_SECONDS  tick interval (default 60)
"""

import logging
import os
import time

from mobile_money_system.backup import BackupManager
from mobile_money_system.database import init_db
from mobile_money_system.logging_config import log_structured, setup_logging
from mobile_money_system.retention import RetentionManager
from mobile_money_system.scheduled import ScheduledPaymentManager
from mobile_money_system.transactions import TransactionManager
from mobile_money_system.users import UserManager


def main() -> None:
    setup_logging()
    init_db()
    tick = float(os.environ.get("MMS_SCHEDULER_TICK_SECONDS", "60"))
    user_manager = UserManager()
    txn_manager = TransactionManager(user_manager)
    scheduled_manager = ScheduledPaymentManager(user_manager, txn_manager)
    retention_manager = RetentionManager()
    backup_manager = BackupManager()
    log_structured("SCHEDULER_WORKER_START", tick_seconds=tick)
    last_retention = 0.0
    while True:
        try:
            results = scheduled_manager.process_due()
            if results:
                log_structured("SCHEDULER_TICK", executed=len(results))
            backup_manager.maybe_auto_backup()
            # Daily maintenance: retention pruning
            if time.time() - last_retention > 86400:
                deleted = retention_manager.run_retention()
                log_structured("RETENTION_RUN", deleted=deleted)
                last_retention = time.time()
        except Exception as e:  # the worker must never die
            log_structured("SCHEDULER_TICK_ERROR", error=str(e), level=logging.ERROR)
        time.sleep(tick)


if __name__ == "__main__":
    main()
