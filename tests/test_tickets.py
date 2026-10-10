"""Tier 4 integrations: support ticketing."""

from mobile_money_system.tickets import TicketManager


def test_create_validation(db_path):
    tm = TicketManager()
    ok, _ = tm.create("+2348012345678", "", "payment", "msg")
    assert not ok
    ok, _ = tm.create("+2348012345678", "Subject", "payment", "")
    assert not ok
    ok, _ = tm.create("+2348012345678", "Subject", "nonsense", "msg")
    assert not ok
    ok, _ = tm.create("+2348012345678", "Subject", "payment", "msg", priority="urgent")
    assert not ok
    ok, msg = tm.create("+2348012345678", "Cannot withdraw", "payment", "ATM ate my card", priority="high")
    assert ok, msg
    t = tm.all_tickets()[0]
    assert t["status"] == "open"
    assert t["priority"] == "high"
    assert t["category"] == "payment"


def test_my_tickets_scoped_to_user(db_path):
    tm = TicketManager()
    tm.create("+2348012345678", "A issue", "account", "msg a")
    tm.create("+2348087654321", "B issue", "kyc", "msg b")
    assert len(tm.my_tickets("+2348012345678")) == 1
    assert len(tm.my_tickets("+2348087654321")) == 1
    assert len(tm.my_tickets("+2349999999999")) == 0


def test_all_tickets_filters(db_path):
    tm = TicketManager()
    tm.create("+2348012345678", "T1", "payment", "m1")
    ok, _ = tm.create("+2348087654321", "T2", "kyc", "m2")
    tid2 = tm.all_tickets()[0]["id"]
    tm.set_status(tid2, "resolved")
    assert len(tm.all_tickets()) == 2
    assert len(tm.all_tickets(status="resolved")) == 1
    assert len(tm.all_tickets(category="payment")) == 1
    assert len(tm.all_tickets(status="open", category="kyc")) == 0


def test_reply_flow(db_path):
    tm = TicketManager()
    tm.create("+2348012345678", "Help", "account", "I am locked out")
    tid = tm.all_tickets()[0]["id"]
    ok, msg = tm.reply(tid, "0000000000", "Try resetting your PIN.")
    assert ok, msg
    t = tm.get(tid)
    assert t["admin_reply"] == "Try resetting your PIN."
    assert t["replied_by"] == "0000000000"
    assert t["replied_at"] is not None
    assert t["status"] == "in_progress"   # open -> in_progress on first reply
    ok, _ = tm.reply(tid, "0000000000", "")
    assert not ok                          # empty reply rejected


def test_set_status(db_path):
    tm = TicketManager()
    tm.create("+2348012345678", "Help", "security", "suspicious login")
    tid = tm.all_tickets()[0]["id"]
    ok, _ = tm.set_status(tid, "resolved", actor_phone="0000000000")
    assert ok
    assert tm.get(tid)["status"] == "resolved"
    ok, _ = tm.set_status(tid, "bogus")
    assert not ok
    ok, _ = tm.set_status(99999, "closed")
    assert not ok
    assert tm.get(tid)["status"] == "resolved"  # unchanged
