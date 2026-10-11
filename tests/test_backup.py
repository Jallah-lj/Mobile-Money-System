"""Professionalism: database backups — snapshot, registry, restore, auto-backup."""

import os

import pytest

import mobile_money_system.backup as backup_module
from mobile_money_system.backup import BackupManager
from mobile_money_system.config import set_setting
from mobile_money_system.users import UserManager


@pytest.fixture()
def bm(db_path, tmp_path, monkeypatch):
    """A BackupManager writing into a tmp directory (not the repo's backups/)."""
    monkeypatch.setattr(backup_module, "BACKUP_DIR", str(tmp_path / "backups"))
    return BackupManager()


def test_backup_and_restore_roundtrip(bm):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")

    ok, path = bm.create_backup(note="test")
    assert ok, path
    assert os.path.isfile(path)

    backups = bm.list_backups()
    assert len(backups) == 1
    assert backups[0]["note"] == "test"
    assert backups[0]["size_bytes"] > 0

    # Mutate the live database, then restore the snapshot
    um.register("+2348087654321", "Bob", "1234", "q", "a")
    assert um.get_user("+2348087654321") is not None

    ok, msg = bm.restore_backup(backups[0]["filename"])
    assert ok, msg
    assert um.get_user("+2348087654321") is None   # Bob is gone
    assert um.get_user("+2348012345678") is not None  # Alice survives


def test_restore_takes_a_safety_backup_first(bm):
    um = UserManager()
    um.register("+2348012345678", "Alice", "1234", "q", "a")
    ok, _path = bm.create_backup(note="original")
    assert ok
    um.register("+2348087654321", "Bob", "1234", "q", "a")

    ok, _msg = bm.restore_backup(bm.list_backups()[0]["filename"])
    assert ok
    # The pre-restore safety snapshot is registered too
    notes = [b["note"] for b in bm.list_backups()]
    assert "pre-restore" in notes


def test_backup_rejects_path_traversal(bm):
    assert bm.backup_path("../mobile_money.db") is None
    assert bm.backup_path("../../etc/passwd") is None
    assert bm.backup_path("no-such-file.db") is None
    assert bm.backup_path("") is None


def test_maybe_auto_backup_runs_once_per_interval(bm):
    set_setting("auto_backup_hours", "24")
    assert bm.maybe_auto_backup() is True   # no backup yet -> create one
    assert bm.maybe_auto_backup() is False  # recent backup -> no-op
    assert len(bm.list_backups()) == 1


def test_maybe_auto_backup_disabled(bm):
    set_setting("auto_backup_hours", "0")
    assert bm.maybe_auto_backup() is False
    assert bm.list_backups() == []
