"""Professionalism: structured JSON-lines logging."""

import json
import logging

import mobile_money_system.logging_config as lc


def test_log_structured_writes_json_line(tmp_path, monkeypatch):
    monkeypatch.setenv("MMS_LOG_DIR", str(tmp_path))
    # Reset module state + handlers so setup uses the tmp log dir
    monkeypatch.setattr(lc, "_configured", False)
    root = logging.getLogger("mms")
    for handler in list(root.handlers):
        root.removeHandler(handler)

    lc.log_structured("TEST_EVENT", amount="42.00", phone="+2348012345678")

    log_file = tmp_path / "mms.log"
    assert log_file.exists()
    line = json.loads(log_file.read_text().strip().splitlines()[-1])
    assert line["message"] == "TEST_EVENT"
    assert line["level"] == "INFO"
    assert line["amount"] == "42.00"
    assert line["phone"] == "+2348012345678"
    assert "ts" in line


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("MMS_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(lc, "_configured", False)
    root = logging.getLogger("mms")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    lc.setup_logging()
    handler_count = len(root.handlers)
    lc.setup_logging()  # second call must not add duplicate handlers
    assert len(root.handlers) == handler_count
