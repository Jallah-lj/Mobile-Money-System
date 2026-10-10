"""Tier 4 integrations: signed webhooks (unit + local end-to-end server)."""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mobile_money_system import webhooks
from mobile_money_system.webhooks import WebhookManager, sign_payload


# --- Signature ---

def test_sign_payload_matches_hmac_sha256():
    body = b'{"event": "TRANSFER"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert sign_payload("secret", body) == expected
    assert sign_payload("secret", body) != sign_payload("other", body)


# --- CRUD ---

def test_webhook_crud_and_validation(db_path):
    wm = WebhookManager()
    ok, _ = wm.add("", "https://x.example", ["TRANSFER"])
    assert not ok                      # empty name
    ok, _ = wm.add("Hook", "ftp://x", ["TRANSFER"])
    assert not ok                      # bad scheme
    ok, _ = wm.add("Hook", "https://x.example", ["NONSENSE"])
    assert not ok                      # bad event
    ok, msg = wm.add("Hook", "https://x.example/hook", ["TRANSFER", "DEPOSIT"])
    assert ok, msg
    hooks = wm.list()
    assert len(hooks) == 1
    assert hooks[0]["events"] == "TRANSFER,DEPOSIT"
    assert hooks[0]["secret"]       # auto-generated
    assert hooks[0]["active"] == 1

    hid = hooks[0]["id"]
    assert wm.set_active(hid, False) is True
    assert wm.get(hid)["active"] == 0
    assert wm.set_active(hid, True) is True
    assert wm.remove(hid) is True
    assert wm.list() == []
    assert wm.remove(hid) is False


# --- Dispatch (mocked transport) ---

def _payload(event="TRANSFER"):
    return {"id": "TXN-1", "sender_phone": "+1", "receiver_phone": "+2",
            "amount": "50.00", "currency": "USD", "type": event}


def test_dispatch_delivers_to_subscribed_active_webhooks(db_path, monkeypatch):
    wm = WebhookManager()
    wm.add("All", "https://a.example/hook", ["TRANSFER", "DEPOSIT"])
    wm.add("TxOnly", "https://b.example/hook", ["TRANSFER"])
    wm.add("DepOnly", "https://c.example/hook", ["DEPOSIT"])
    # Deactivate the DEPOSIT-only hook (list() is newest-first — find by URL)
    dep_only = next(h for h in wm.list() if h["url"] == "https://c.example/hook")
    wm.set_active(dep_only["id"], False)

    calls = []

    def fake_post(url, body, headers, timeout=5):
        calls.append((url, body, json.loads(body), headers))
        return 200, ""

    monkeypatch.setattr(webhooks, "_post", fake_post)
    results = wm.dispatch("TRANSFER", _payload())

    urls = sorted(c[0] for c in calls)
    assert urls == ["https://a.example/hook", "https://b.example/hook"]
    # Signed headers present and verifiable — each against its own webhook's secret
    secrets = {h["url"]: h["secret"] for h in wm.list()}
    for url, raw_body, body, headers in calls:
        assert headers["X-MMS-Event"] == "TRANSFER"
        assert headers["Content-Type"] == "application/json"
        assert body["event"] == "TRANSFER"
        assert body["data"]["id"] == "TXN-1"
        expected = "sha256=" + sign_payload(secrets[url], raw_body)
        assert headers["X-MMS-Signature"] == expected
    # Deliveries recorded
    deliveries = wm.recent_deliveries()
    assert len(deliveries) == 2
    assert all(d["status_code"] == 200 and d["attempts"] == 1 for d in deliveries)


def test_dispatch_retries_server_errors_but_not_4xx(db_path, monkeypatch):
    wm = WebhookManager()
    wm.add("Flaky", "https://flaky.example/hook", ["TRANSFER"])
    attempts = {"n": 0}

    def fake_post_500(url, body, headers, timeout=5):
        attempts["n"] += 1
        return 500, "HTTP 500"

    monkeypatch.setattr(webhooks, "_post", fake_post_500)
    monkeypatch.setattr(webhooks, "RETRY_BACKOFF_SECONDS", (0, 0))  # no waiting in tests
    results = wm.dispatch("TRANSFER", _payload())
    assert attempts["n"] == webhooks.MAX_ATTEMPTS == 3
    assert results[0]["status_code"] == 500
    assert wm.recent_deliveries()[0]["attempts"] == 3

    # 4xx: no retry
    wm2_calls = {"n": 0}

    def fake_post_400(url, body, headers, timeout=5):
        wm2_calls["n"] += 1
        return 400, "HTTP 400"

    monkeypatch.setattr(webhooks, "_post", fake_post_400)
    wm.dispatch("TRANSFER", _payload())
    assert wm2_calls["n"] == 1


def test_dispatch_network_error_recorded(db_path, monkeypatch):
    wm = WebhookManager()
    wm.add("Down", "https://down.example/hook", ["TRANSFER"])
    monkeypatch.setattr(webhooks, "_post",
                        lambda url, body, headers, timeout=5: (None, "connection refused"))
    monkeypatch.setattr(webhooks, "RETRY_BACKOFF_SECONDS", (0, 0))
    results = wm.dispatch("TRANSFER", _payload())
    assert results[0]["status_code"] is None
    assert results[0]["attempts"] == 3
    d = wm.recent_deliveries()[0]
    assert d["error"] == "connection refused"


# --- End-to-end with a real local HTTP server ---

def test_dispatch_end_to_end_local_server(db_path):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append({
                "path": self.path,
                "signature": self.headers.get("X-MMS-Signature"),
                "event": self.headers.get("X-MMS-Event"),
                "body": self.rfile.read(length),
            })
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        wm = WebhookManager()
        ok, msg = wm.add("Local", f"http://127.0.0.1:{port}/hook", ["TRANSFER"])
        assert ok, msg
        hook = wm.list()[0]
        results = wm.dispatch("TRANSFER", _payload())
        assert results[0]["status_code"] == 200
        assert len(received) == 1
        assert received[0]["path"] == "/hook"
        assert received[0]["event"] == "TRANSFER"
        # Verify the signature over the exact bytes received
        expected = "sha256=" + sign_payload(hook["secret"], received[0]["body"])
        assert received[0]["signature"] == expected
        body = json.loads(received[0]["body"])
        assert body["data"]["id"] == "TXN-1"
    finally:
        server.shutdown()
        server.server_close()
