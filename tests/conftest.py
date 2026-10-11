import os
import sys

import pytest

# Make the package importable when running pytest from the repo root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import mobile_money_system.database as database


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """Point the whole system at a fresh, isolated SQLite database per test."""
    path = str(tmp_path / "test_mobile_money.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    return path


@pytest.fixture()
def managers(db_path):
    """A fresh UserManager + TransactionManager backed by the temp database."""
    from mobile_money_system.transactions import TransactionManager
    from mobile_money_system.users import UserManager
    user_manager = UserManager()
    txn_manager = TransactionManager(user_manager)
    return user_manager, txn_manager


@pytest.fixture()
def verified_user(managers):
    """Register + KYC-verify a user with a funded wallet. Returns (phone, user_manager, txn_manager)."""
    user_manager, txn_manager = managers
    phone = "+2348012345678"
    success, msg = user_manager.register(phone, "Alice", "1234", "q", "a")
    assert success, msg
    user_manager.submit_kyc(phone, "passport", "AB1234567")
    # Fund via admin credit (deposits are subject to the universal per-transaction limits)
    txn_manager.admin_adjust_balance(phone, 10000.0, "test seed")
    return phone, user_manager, txn_manager


@pytest.fixture()
def second_verified_user(managers):
    """A second registered + verified user (receiver)."""
    user_manager, txn_manager = managers
    phone = "+2348087654321"
    success, msg = user_manager.register(phone, "Bob", "1234", "q", "a")
    assert success, msg
    user_manager.submit_kyc(phone, "passport", "CD7654321")
    return phone, user_manager, txn_manager
