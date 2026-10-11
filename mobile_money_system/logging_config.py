"""Structured JSON-lines logging to logs/mms.log (plus stdout).

The audit_log database table remains the security/compliance trail; this file
log is the operational one (boot, scheduler ticks, retention runs, backups,
API requests). One JSON object per line, UTC timestamps, extra fields inline.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

_configured = False

# Attributes every LogRecord has — anything else in __dict__ is a structured field
_STANDARD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the mms logger once per process. Returns the root mms logger."""
    global _configured
    logger = logging.getLogger("mms")
    if _configured:
        return logger
    log_dir = os.environ.get("MMS_LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger.setLevel(level)
    file_handler = logging.FileHandler(os.path.join(log_dir, "mms.log"))
    file_handler.setFormatter(JsonLineFormatter())
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    _configured = True
    return logger


def get_logger(name: str = "app") -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"mms.{name}")


def log_structured(event: str, level: int = logging.INFO, **fields) -> None:
    """Write one structured log line: log_structured("TRANSFER", amount=..., phone=...)"""
    get_logger("app").log(level, event, extra=fields)
