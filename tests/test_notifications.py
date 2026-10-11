"""Tier 4 integrations: notification channels & providers."""

from mobile_money_system.notifications import (
    ConsoleProvider,
    EmailProvider,
    NotificationService,
    build_message,
)


class FakeProvider:
    def __init__(self):
        self.sent = []

    def send_sms(self, destination, message):
        self.sent.append(("sms", destination, message))
        return True, "fake"

    def send_email(self, destination, subject, message):
        self.sent.append(("email", destination, subject, message))
        return True, "fake"


def _service(um, sms=None, email=None):
    return NotificationService(um, sms_provider=sms or FakeProvider(),
                               email_provider=email or FakeProvider())


def test_add_channel_validation(managers, verified_user):
    phone, um, tm = verified_user
    ns = _service(um)
    ok, _ = ns.add_channel(phone, "sms", "not-a-phone")
    assert not ok
    ok, _ = ns.add_channel(phone, "email", "not-an-email")
    assert not ok
    ok, _ = ns.add_channel(phone, "fax", "+2348012345678")
    assert not ok
    ok, _ = ns.add_channel(phone, "sms", "")
    assert not ok
    ok, msg = ns.add_channel(phone, "sms", "+2348087654321")
    assert ok, msg
    ok, _ = ns.add_channel(phone, "sms", "+2348087654321")  # duplicate
    assert not ok
    ok, msg = ns.add_channel(phone, "email", "alice@example.com")
    assert ok, msg
    channels = ns.list_channels(phone)
    assert len(channels) == 2


def test_channel_remove_and_toggle(managers, verified_user):
    phone, um, tm = verified_user
    ns = _service(um)
    ns.add_channel(phone, "sms", "+2348087654321")
    cid = ns.list_channels(phone)[0]["id"]
    assert ns.set_channel_enabled(phone, cid, False) is True
    assert ns.list_channels(phone)[0]["enabled"] == 0
    assert ns.remove_channel(phone, cid) is True
    assert ns.list_channels(phone) == []
    # Scoped to owner
    assert ns.remove_channel("+2349999999999", cid) is False


def test_notify_transfer_reaches_both_parties(managers, verified_user, second_verified_user):
    phone, um, tm = verified_user
    bob_phone, _, _ = second_verified_user
    sms, email = FakeProvider(), FakeProvider()
    ns = _service(um, sms, email)
    ns.add_channel(phone, "sms", "+2348011111111")
    ns.add_channel(bob_phone, "email", "bob@example.com")

    payload = {"id": "TXN-9", "sender_phone": phone, "receiver_phone": bob_phone,
               "amount": "75.00", "currency": "USD", "type": "TRANSFER", "description": "lunch"}
    results = ns.notify("TRANSFER", payload)

    assert len(results) == 2
    assert ("sms", "+2348011111111", "You sent USD 75.00 to " + bob_phone + ". lunch Ref: TXN-9") in sms.sent
    assert ("email", "bob@example.com", "Money received",
            f"You received USD 75.00 from {phone}. lunch Ref: TXN-9") in email.sent


def test_notify_skips_disabled_channels_and_unknown_users(managers, verified_user):
    phone, um, tm = verified_user
    sms = FakeProvider()
    ns = _service(um, sms=sms)
    ns.add_channel(phone, "sms", "+2348011111111")
    cid = ns.list_channels(phone)[0]["id"]
    ns.set_channel_enabled(phone, cid, False)

    payload = {"id": "TXN-1", "sender_phone": phone, "receiver_phone": "SYSTEM",
               "amount": "10.00", "currency": "USD", "type": "WITHDRAWAL", "description": ""}
    results = ns.notify("WITHDRAWAL", payload)
    assert results == []          # disabled channel + SYSTEM is not a user
    assert sms.sent == []


def test_build_message_templates():
    p = {"id": "T1", "sender_phone": "+1", "receiver_phone": "+2",
         "amount": "5.00", "currency": "USD", "type": "TRANSFER", "description": "x"}
    assert build_message("TRANSFER", p, "+1")[1].startswith("You sent USD 5.00 to +2")
    assert build_message("TRANSFER", p, "+2")[1].startswith("You received USD 5.00 from +1")
    assert build_message("TRANSFER", p, "+3") is None
    dep = {"id": "T2", "sender_phone": "SYSTEM", "receiver_phone": "+2",
           "amount": "100.00", "currency": "USD", "type": "DEPOSIT", "description": ""}
    assert build_message("DEPOSIT", dep, "+2")[0] == "Deposit successful"
    assert build_message("DEPOSIT", dep, "SYSTEM") is None


def test_console_provider_logs_and_succeeds(db_path):
    provider = ConsoleProvider()
    ok, detail = provider.send_sms("+2348011111111", "hello")
    assert ok and detail == "console"
    ok, detail = provider.send_email("a@b.com", "Subj", "body")
    assert ok and detail == "console"


def test_email_provider_falls_back_to_console_when_unconfigured(db_path, monkeypatch):
    monkeypatch.delenv("MMS_SMTP_HOST", raising=False)
    provider = EmailProvider()
    assert provider.configured is False
    ok, detail = provider.send_email("a@b.com", "Subj", "body")
    assert ok and detail == "console"
