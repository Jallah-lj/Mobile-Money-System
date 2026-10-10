"""Tier 2 money features: scheduled & recurring payments."""

from datetime import timedelta

from mobile_money_system.models import utcnow
from mobile_money_system.scheduled import ScheduledPaymentManager, _next_run


def _make_scheduler(managers):
    um, tm = managers
    return ScheduledPaymentManager(um, tm), um, tm


def test_create_validates_input(managers, verified_user):
    phone, um, tm = verified_user
    spm, _, _ = _make_scheduler(managers)

    ok, _ = spm.create(phone, "TRANSFER", 0)          # bad amount
    assert not ok
    ok, _ = spm.create(phone, "TRANSFER", -5)         # negative
    assert not ok
    ok, _ = spm.create(phone, "TRANSFER", 10, frequency="hourly")  # bad frequency
    assert not ok
    ok, _ = spm.create(phone, "TRANSFER", 10, receiver_phone="+2349999999999")  # unknown receiver
    assert not ok
    ok, _ = spm.create(phone, "TRANSFER", 10, receiver_phone=phone)  # self
    assert not ok
    ok, _ = spm.create(phone, "BILL_PAYMENT", 10)     # missing biller fields
    assert not ok
    assert spm.list(phone) == []


def test_process_due_executes_due_transfer(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    spm, _, _ = _make_scheduler(managers)

    past = (utcnow() - timedelta(minutes=5)).isoformat()
    ok, msg = spm.create(phone, "TRANSFER", 100, "rent", receiver_phone=bob_phone,
                         frequency="once", start_at=past)
    assert ok, msg

    results = spm.process_due()
    assert len(results) == 1 and results[0]["ok"] is True

    # Money actually moved
    assert um.get_user(phone).balance == 10000 - 100
    assert um.get_user(bob_phone).balance == 100

    # 'once' deactivated after firing
    payments = spm.list(phone)
    assert payments[0]["active"] == 0
    assert payments[0]["last_status"].startswith("OK")
    assert payments[0]["last_run_at"] is not None

    # Second tick does not double-fire
    assert spm.process_due() == []


def test_process_due_skips_future_payments(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    spm, _, _ = _make_scheduler(managers)

    future = (utcnow() + timedelta(days=1)).isoformat()
    spm.create(phone, "TRANSFER", 100, receiver_phone=bob_phone, start_at=future)
    assert spm.process_due() == []
    assert um.get_user(phone).balance == 10000
    assert spm.list(phone)[0]["active"] == 1


def test_recurring_advances_next_run(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    spm, _, _ = _make_scheduler(managers)

    past = (utcnow() - timedelta(minutes=5)).isoformat()
    spm.create(phone, "TRANSFER", 10, receiver_phone=bob_phone, frequency="daily", start_at=past)
    spm.process_due()
    p = spm.list(phone)[0]
    assert p["active"] == 1
    # Next run is ~1 day after the execution time
    from datetime import datetime
    next_run = datetime.fromisoformat(p["next_run_at"])
    assert next_run > utcnow()


def test_failed_payment_deactivates_and_records_status(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    spm, _, _ = _make_scheduler(managers)

    past = (utcnow() - timedelta(minutes=5)).isoformat()
    # More than the balance -> transfer fails
    spm.create(phone, "TRANSFER", 999999, receiver_phone=bob_phone, frequency="daily", start_at=past)
    results = spm.process_due()
    assert len(results) == 1 and results[0]["ok"] is False
    p = spm.list(phone)[0]
    assert p["active"] == 0
    assert p["last_status"].startswith("FAILED")
    assert um.get_user(phone).balance == 10000  # untouched


def test_pause_resume_cancel(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    spm, _, _ = _make_scheduler(managers)

    past = (utcnow() - timedelta(minutes=5)).isoformat()
    spm.create(phone, "TRANSFER", 10, receiver_phone=bob_phone, start_at=past)
    sp_id = spm.list(phone)[0]["id"]

    # Pause -> not executed
    ok, _ = spm.set_active(phone, sp_id, False)
    assert ok
    assert spm.process_due() == []

    # Resume -> executes
    ok, _ = spm.set_active(phone, sp_id, True)
    assert ok
    assert len(spm.process_due()) == 1

    # Cancel -> gone from execution, record kept
    spm.create(phone, "TRANSFER", 10, receiver_phone=bob_phone, start_at=past)
    sp_id2 = [p for p in spm.list(phone) if p["active"] == 1][0]["id"]
    ok, _ = spm.cancel(phone, sp_id2)
    assert ok
    assert spm.process_due() == []
    assert spm.list(phone)[-1]["last_status"] == "CANCELLED"

    # Scoped to owner
    assert spm.cancel(bob_phone, sp_id) == (False, "Scheduled payment not found.")


def test_bill_payment_scheduled(managers, verified_user):
    phone, um, tm = verified_user
    spm, _, _ = _make_scheduler(managers)
    past = (utcnow() - timedelta(minutes=5)).isoformat()
    ok, msg = spm.create(phone, "BILL_PAYMENT", 20, "electricity",
                         biller_name="LEC Power", biller_id="MTR-123",
                         frequency="monthly", start_at=past)
    assert ok, msg
    results = spm.process_due()
    assert len(results) == 1 and results[0]["ok"] is True
    # 20 + 0.25 flat bill fee
    assert um.get_user(phone).balance == 10000 - 20 - 0.25


def test_next_run_helper():
    from datetime import datetime
    base = datetime(2026, 10, 10, 12, 0, 0)
    assert _next_run("once", base) is None
    assert datetime.fromisoformat(_next_run("daily", base)) == base + timedelta(days=1)
    assert datetime.fromisoformat(_next_run("weekly", base)) == base + timedelta(weeks=1)
    assert _next_run("monthly", base) == "2026-11-10T12:00:00"
    # Month-end clamping: Jan 31 -> Feb 28
    assert _next_run("monthly", datetime(2026, 1, 31)) == "2026-02-28T00:00:00"
