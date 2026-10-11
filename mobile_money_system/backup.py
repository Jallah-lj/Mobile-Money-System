"""Database backups: snapshot + restore via SQLite's online backup API.

Backups are plain SQLite files in the backups/ directory (gitignored), with
metadata registered in the `backups` table. The online backup API is safe to
run against a live database — it copies page-by-page without blocking
writers for long, and handles WAL correctly.
"""

import os
import sqlite3
from datetime import datetime

if __package__:
    from . import database
    from .config import get_float, get_setting, set_setting
    from .database import get_db, init_db
    from .models import utcnow
else:
    import database  # type: ignore[no-redef]
    from config import get_float, get_setting, set_setting  # type: ignore[no-redef]
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]

BACKUP_DIR = os.environ.get("MMS_BACKUP_DIR", "backups")


class BackupManager:
    def __init__(self):
        init_db()
        os.makedirs(BACKUP_DIR, exist_ok=True)

    @staticmethod
    def _db_path() -> str:
        # Read the module global at call time so tests can patch DB_PATH.
        return database.DB_PATH

    def create_backup(self, note: str = "") -> tuple[bool, str]:
        """Snapshot the live database. Returns (ok, path-or-error)."""
        os.makedirs(BACKUP_DIR, exist_ok=True)
        filename = f"mms-backup-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
        dest = os.path.join(BACKUP_DIR, filename)
        try:
            src = sqlite3.connect(self._db_path())
            dst = sqlite3.connect(dest)
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
        except sqlite3.Error as e:
            return False, f"Backup failed: {e}"
        with get_db() as conn:
            conn.execute(
                "INSERT INTO backups (filename, size_bytes, created_at, note) VALUES (?, ?, ?, ?)",
                (filename, os.path.getsize(dest), utcnow().isoformat(), note))
            conn.commit()
        set_setting("last_backup_at", utcnow().isoformat())
        return True, dest

    def list_backups(self) -> list[dict]:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM backups ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def backup_path(self, filename: str) -> str | None:
        """Resolve a backup filename to a path, rejecting path traversal."""
        if not filename or os.path.basename(filename) != filename or ".." in filename:
            return None
        path = os.path.join(BACKUP_DIR, filename)
        return path if os.path.isfile(path) else None

    def restore_backup(self, filename: str) -> tuple[bool, str]:
        """Restore a backup over the live database.

        A safety snapshot of the current database is taken first
        (note='pre-restore'), so a bad restore is itself recoverable.
        """
        path = self.backup_path(filename)
        if not path:
            return False, "Backup not found"
        # Safety net: snapshot the current state before overwriting it
        ok, safety = self.create_backup(note="pre-restore")
        if not ok:
            return False, "Could not take the pre-restore safety backup"
        try:
            src = sqlite3.connect(path)
            dst = sqlite3.connect(self._db_path())
            with dst:
                src.backup(dst)
            dst.close()
            src.close()
        except sqlite3.Error as e:
            return False, f"Restore failed: {e}"
        # The restore rewinds the backups registry to the snapshot's state —
        # re-register the safety snapshot so it stays discoverable.
        safety_name = os.path.basename(safety)
        if self.backup_path(safety_name):
            with get_db() as conn:
                row = conn.execute(
                    "SELECT id FROM backups WHERE filename = ?", (safety_name,)).fetchone()
                if not row:
                    conn.execute(
                        "INSERT INTO backups (filename, size_bytes, created_at, note) VALUES (?, ?, ?, ?)",
                        (safety_name, os.path.getsize(safety), utcnow().isoformat(), "pre-restore"))
                    conn.commit()
        return True, f"Database restored from {filename}"

    def maybe_auto_backup(self) -> bool:
        """Create a backup if the last one is older than auto_backup_hours.

        Returns True if a backup was created. Called on app runs; cheap when
        a recent backup exists (one SELECT).
        """
        max_age_hours = get_float("auto_backup_hours", 24)
        if max_age_hours <= 0:
            return False
        last = get_setting("last_backup_at", "")
        if last:
            try:
                age_hours = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600
                if age_hours < max_age_hours:
                    return False
            except ValueError:
                pass
        ok, _ = self.create_backup(note="auto")
        return ok
