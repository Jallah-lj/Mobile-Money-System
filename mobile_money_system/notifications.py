"""Out-of-app notifications (SMS / email) via pluggable providers.

Users register notification channels (SMS number or email address) in
Settings. When a transaction event fires, the NotificationService looks up
both parties' enabled channels and delivers a human-readable message through
the matching provider:

  * ConsoleProvider — always available; records the message in the audit
    log (used in development and as the default).
  * EmailProvider — real SMTP delivery when MMS_SMTP_HOST is configured
    (plus MMS_SMTP_PORT / MMS_SMTP_USER / MMS_SMTP_PASSWORD / MMS_SMTP_FROM);
    falls back to the console provider when SMTP is not configured.

An SMS provider for a real gateway (Twilio, Africa's Talking, ...) implements
the same ``send_sms(destination, message)`` interface as ConsoleProvider.
"""

import os

if __package__:
    from .audit import log_event
    from .database import get_db, init_db
    from .models import utcnow
    from .users import UserManager
else:
    from audit import log_event  # type: ignore[no-redef]
    from database import get_db, init_db  # type: ignore[no-redef]
    from models import utcnow  # type: ignore[no-redef]
    from users import UserManager  # type: ignore[no-redef]

CHANNELS = ("sms", "email")


class ConsoleProvider:
    """Development provider: records every message in the audit log."""

    name = "console"

    def send_sms(self, destination: str, message: str) -> tuple[bool, str]:
        log_event("NOTIFY", "SMS_SENT", target=destination, details=message[:200])
        print(f"[SMS -> {destination}] {message}")
        return True, "console"

    def send_email(self, destination: str, subject: str, message: str) -> tuple[bool, str]:
        log_event("NOTIFY", "EMAIL_SENT", target=destination, details=f"{subject}: {message[:200]}")
        print(f"[EMAIL -> {destination}] {subject}\n{message}")
        return True, "console"


class EmailProvider:
    """SMTP email provider; falls back to console when SMTP is not configured."""

    name = "smtp"

    def __init__(self):
        self.host = os.environ.get("MMS_SMTP_HOST")
        self.port = int(os.environ.get("MMS_SMTP_PORT", "587"))
        self.user = os.environ.get("MMS_SMTP_USER")
        self.password = os.environ.get("MMS_SMTP_PASSWORD")
        self.from_addr = os.environ.get("MMS_SMTP_FROM", "noreply@mobilemoney.local")
        self._console = ConsoleProvider()

    @property
    def configured(self) -> bool:
        return bool(self.host)

    def send_email(self, destination: str, subject: str, message: str) -> tuple[bool, str]:
        if not self.configured:
            return self._console.send_email(destination, subject, message)
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = destination
        msg.set_content(message)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                server.starttls()
                if self.user:
                    server.login(self.user, self.password)
                server.send_message(msg)
            log_event("NOTIFY", "EMAIL_SENT", target=destination, details=subject)
            return True, "smtp"
        except Exception as e:
            log_event("NOTIFY", "EMAIL_FAILED", target=destination, details=str(e), status="FAILURE")
            return False, str(e)

    def send_sms(self, destination: str, message: str) -> tuple[bool, str]:
        return self._console.send_sms(destination, message)


def build_message(event: str, payload: dict, for_phone: str) -> tuple[str, str] | None:
    """Human-readable (subject, body) for a transaction event, or None."""
    amount = f"{payload.get('currency', 'USD')} {float(payload.get('amount', 0)):,.2f}"
    sender, receiver = payload.get("sender_phone", ""), payload.get("receiver_phone", "")
    desc = payload.get("description") or ""
    ref = payload.get("id", "")

    if event == "TRANSFER":
        if for_phone == sender:
            return ("Money sent", f"You sent {amount} to {receiver}. {desc} Ref: {ref}")
        if for_phone == receiver:
            return ("Money received", f"You received {amount} from {sender}. {desc} Ref: {ref}")
    elif event == "DEPOSIT":
        if for_phone == receiver:
            return ("Deposit successful", f"Your account was credited with {amount}. Ref: {ref}")
    elif event == "WITHDRAWAL":
        if for_phone == sender:
            return ("Withdrawal successful", f"You withdrew {amount} from your wallet. Ref: {ref}")
    elif event == "BILL_PAYMENT":
        if for_phone == sender:
            return ("Bill paid", f"Payment of {amount} ({desc}) was successful. Ref: {ref}")
    elif event == "REQUEST":
        if for_phone == sender:  # the payer
            return ("Money request", f"{receiver} requested {amount} from you. {desc} Ref: {ref}")
        if for_phone == receiver:  # the requester
            return ("Request sent", f"You requested {amount} from {sender}. Ref: {ref}")
    return None


class NotificationService:
    def __init__(self, user_manager: UserManager, sms_provider=None, email_provider=None):
        self.user_manager = user_manager
        self.sms_provider = sms_provider or ConsoleProvider()
        self.email_provider = email_provider or EmailProvider()
        init_db()  # Ensure schema exists (safe on fresh databases)

    # --- Channel management (user-facing, in Settings) ---

    def add_channel(self, phone: str, channel: str, destination: str) -> tuple[bool, str]:
        channel = (channel or "").lower().strip()
        destination = (destination or "").strip()
        if channel not in CHANNELS:
            return False, f"Channel must be one of {CHANNELS}"
        if not destination:
            return False, "Destination is required"
        if channel == "email" and ("@" not in destination or "." not in destination):
            return False, "Enter a valid email address"
        if channel == "sms" and not self.user_manager.validate_phone(destination):
            return False, "Enter a valid phone number (+countrycode...)"
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM notification_channels WHERE phone = ? AND channel = ? AND destination = ?",
                           (phone, channel, destination))
            if cursor.fetchone():
                return False, "This channel is already registered."
            cursor.execute('''
            INSERT INTO notification_channels (phone, channel, destination, enabled, created_at)
            VALUES (?, ?, ?, 1, ?)
            ''', (phone, channel, destination, utcnow().isoformat()))
            conn.commit()
        return True, f"{channel.upper()} notifications enabled for {destination}."

    def list_channels(self, phone: str) -> list[dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM notification_channels WHERE phone = ? ORDER BY created_at", (phone,))
            return [dict(r) for r in cursor.fetchall()]

    def remove_channel(self, phone: str, channel_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM notification_channels WHERE id = ? AND phone = ?",
                           (channel_id, phone))
            changed = cursor.rowcount
            conn.commit()
        return changed > 0

    def set_channel_enabled(self, phone: str, channel_id: int, enabled: bool) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE notification_channels SET enabled = ? WHERE id = ? AND phone = ?",
                           (1 if enabled else 0, channel_id, phone))
            changed = cursor.rowcount
            conn.commit()
        return changed > 0

    # --- Event delivery ---

    def notify(self, event: str, payload: dict) -> list[dict]:
        """Deliver notifications for a transaction event to both parties.

        Returns a list of delivery result dicts. Never raises.
        """
        results = []
        recipients = {p for p in (payload.get("sender_phone"), payload.get("receiver_phone"))
                      if isinstance(p, str) and p}
        for phone in recipients:
            user = self.user_manager.get_user(phone)
            if not user:
                continue
            message = build_message(event, payload, phone)
            if not message:
                continue
            subject, body = message
            for channel in self.list_channels(phone):
                if not channel["enabled"]:
                    continue
                try:
                    if channel["channel"] == "sms":
                        ok, detail = self.sms_provider.send_sms(channel["destination"], body)
                    else:
                        ok, detail = self.email_provider.send_email(channel["destination"], subject, body)
                except Exception as e:
                    ok, detail = False, str(e)
                results.append({"phone": phone, "channel": channel["channel"],
                                "destination": channel["destination"],
                                "ok": ok, "detail": detail})
        return results


def notify_event(event: str, payload: dict, service: NotificationService) -> list[dict]:
    """Convenience wrapper used as a TransactionManager event listener."""
    return service.notify(event, payload)
