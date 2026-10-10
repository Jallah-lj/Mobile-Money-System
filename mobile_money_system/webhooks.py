"""Outbound webhooks — signed event push for external integrations.

Admins register webhook endpoints (URL + secret + subscribed events). Every
transaction event (TRANSFER, DEPOSIT, WITHDRAWAL, BILL_PAYMENT, REQUEST) is
POSTed to each subscribed, active endpoint as JSON with an HMAC-SHA256
signature header (``X-MMS-Signature: sha256=<hex>``) so receivers can verify
authenticity. Deliveries are retried (3 attempts, short backoff) and every
attempt is recorded in the delivery log for debugging.
"""

import hashlib
import hmac
import json
import secrets
import time
import urllib.request
import urllib.error
import uuid
from typing import Dict, List, Optional, Tuple

try:
    from models import utcnow
    from database import get_db, init_db
    from audit import log_event
except ImportError:
    from mobile_money_system.models import utcnow
    from mobile_money_system.database import get_db, init_db
    from mobile_money_system.audit import log_event

ALL_EVENTS = ("TRANSFER", "DEPOSIT", "WITHDRAWAL", "BILL_PAYMENT", "REQUEST")

DELIVERY_TIMEOUT_SECONDS = 5
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (1, 2)  # between attempts


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 hex signature of the raw request body."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, headers: Dict[str, str],
          timeout: float = DELIVERY_TIMEOUT_SECONDS) -> Tuple[Optional[int], str]:
    """POST JSON to a webhook URL. Returns (status_code, error)."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, ""
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP {e.code}"
    except Exception as e:  # connection refused, DNS, timeout, ...
        return None, str(e)


class WebhookManager:
    def __init__(self):
        init_db()  # Ensure schema exists (safe on fresh databases)

    def add(self, name: str, url: str, events: List[str],
            secret: Optional[str] = None) -> Tuple[bool, str]:
        """Register a webhook endpoint. Returns (success, message)."""
        name = (name or "").strip()
        url = (url or "").strip()
        if not name or not url:
            return False, "Name and URL are required."
        if not url.startswith(("http://", "https://")):
            return False, "URL must start with http:// or https://"
        invalid = [e for e in events if e not in ALL_EVENTS]
        if not events or invalid:
            return False, f"Invalid events {invalid}. Valid: {ALL_EVENTS}"
        secret = secret or secrets.token_hex(24)
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO webhooks (name, url, secret, events, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ''', (name, url, secret, ",".join(events), utcnow().isoformat()))
            conn.commit()
        log_event("ADMIN", "WEBHOOK_ADDED", target=url, details=f"{name} events={events}")
        return True, f"Webhook '{name}' registered (secret: {secret}). Save it — it is shown only once."

    def list(self) -> List[Dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhooks ORDER BY created_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def get(self, webhook_id: int) -> Optional[Dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def remove(self, webhook_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            changed = cursor.rowcount
            conn.commit()
        if changed:
            log_event("ADMIN", "WEBHOOK_REMOVED", target=str(webhook_id))
        return changed > 0

    def set_active(self, webhook_id: int, active: bool) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE webhooks SET active = ? WHERE id = ?",
                           (1 if active else 0, webhook_id))
            changed = cursor.rowcount
            conn.commit()
        return changed > 0

    def recent_deliveries(self, webhook_id: Optional[int] = None,
                          limit: int = 50) -> List[Dict]:
        with get_db() as conn:
            cursor = conn.cursor()
            if webhook_id is None:
                cursor.execute(
                    "SELECT * FROM webhook_deliveries ORDER BY id DESC LIMIT ?", (limit,))
            else:
                cursor.execute(
                    "SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
                    (webhook_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    def _record_delivery(self, webhook_id: int, event: str, payload: str,
                         status_code: Optional[int], attempts: int, error: str) -> None:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO webhook_deliveries
                (webhook_id, event, payload, status_code, attempts, delivered_at, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (webhook_id, event, payload, status_code, attempts,
                  utcnow().isoformat(), error))
            conn.commit()

    def dispatch(self, event: str, payload: Dict) -> List[Dict]:
        """Deliver an event to every active webhook subscribed to it.

        Returns a list of per-webhook result dicts. Never raises — delivery
        problems are recorded in the delivery log.
        """
        results = []
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM webhooks WHERE active = 1")
            hooks = [dict(r) for r in cursor.fetchall()]

        body = json.dumps({"event": event, "data": payload,
                           "timestamp": utcnow().isoformat()}).encode()
        delivery_id = uuid.uuid4().hex

        for hook in hooks:
            subscribed = [e.strip() for e in hook["events"].split(",")]
            if event not in subscribed:
                continue
            headers = {
                "Content-Type": "application/json",
                "X-MMS-Event": event,
                "X-MMS-Delivery": delivery_id,
                "X-MMS-Signature": "sha256=" + sign_payload(hook["secret"], body),
            }
            status_code, error, attempts = None, "", 0
            for attempt in range(1, MAX_ATTEMPTS + 1):
                attempts = attempt
                status_code, error = _post(hook["url"], body, headers)
                if status_code is not None and 200 <= status_code < 300:
                    error = ""
                    break
                # Retry only on server errors / network failures, not on 4xx
                if status_code is not None and 400 <= status_code < 500:
                    break
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)])
            self._record_delivery(hook["id"], event, body.decode(), status_code,
                                  attempts, error)
            results.append({"webhook_id": hook["id"], "name": hook["name"],
                            "event": event, "status_code": status_code,
                            "attempts": attempts, "error": error})
        return results


def dispatch_event(event: str, payload: Dict, manager: Optional[WebhookManager] = None) -> List[Dict]:
    """Convenience wrapper used as a TransactionManager event listener."""
    return (manager or WebhookManager()).dispatch(event, payload)
