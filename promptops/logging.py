"""Structured application logging with secret redaction.

Secrets must never reach stdout, the log file, an API response or a Run log.
``redact_text`` and ``redact_mapping`` are the only sanctioned ways to log
values that might contain credentials.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping

from promptops.config import Settings

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "secret_key",
    "secret_ciphertext",
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "credential",
    "credentials",
}

_AUTH_HEADER_RE = re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9._~+/=-]+")
_URL_USERINFO_RE = re.compile(r"(?i)\b(https?://)[^/@\s:]+:[^/@\s]+@")
_KEY_VALUE_RE = re.compile(r"(?i)\b(password|passwd|secret|token|api_key)\s*[=:]\s*[^\s,;'\"]+")


def redact_text(value: str | None) -> str | None:
    """Mask credentials embedded in free text."""

    if value is None:
        return None
    text = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)} ***", str(value))
    text = _URL_USERINFO_RE.sub(r"\1***:***@", text)
    text = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text


def redact_mapping(value: Any) -> Any:
    """Recursively redact sensitive mapping keys (for log extras / details)."""

    if isinstance(value, Mapping):
        return {
            key: ("***" if str(key).lower() in _SENSITIVE_KEYS else redact_mapping(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactionFilter(logging.Filter):
    """Redact the rendered message and supported extra fields in-place."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - stdlib API
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = ()
        for key in list(record.__dict__):
            if key.lower() in _SENSITIVE_KEYS:
                record.__dict__[key] = "***"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; keeps the fields named in the SPEC."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for key in ("run_id", "task_id", "endpoint_id", "phase", "exc_info"):
            value = record.__dict__.get(key)
            if value:
                payload[key] = redact_mapping(value)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Configure root logging once (stdout + rotating file)."""

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter()
    redaction = RedactionFilter()

    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(redaction)
    root.addHandler(stream)

    settings.logs_path.mkdir(parents=True, exist_ok=True)
    log_file: Path = settings.logs_path / "app.log"
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redaction)
    root.addHandler(file_handler)

    # Keep noisy third-party libraries quieter than the app.
    logging.getLogger("httpx").setLevel(max(level, logging.WARNING))
    logging.getLogger("aiosqlite").setLevel(max(level, logging.WARNING))
