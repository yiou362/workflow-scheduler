"""Time helpers: UTC epoch milliseconds and the single global UTC offset.

The product stores every instant as UTC epoch milliseconds and interprets all
schedule rules in one fixed offset (default ``+08:00``).  No IANA zones, no DST.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class Clock(Protocol):
    """Injectable clock so tests never depend on ``sleep``."""

    def now_ms(self) -> int: ...


class SystemClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)


class FixedClock:
    """Test clock: ``advance`` moves time forward deterministically."""

    def __init__(self, start_ms: int) -> None:
        self._now = int(start_ms)

    def now_ms(self) -> int:
        return self._now

    def advance(self, delta_ms: int) -> int:
        self._now += int(delta_ms)
        return self._now

    def set(self, value_ms: int) -> int:
        self._now = int(value_ms)
        return self._now


def now_ms() -> int:
    return int(time.time() * 1000)


def parse_utc_offset(value: str) -> timezone:
    """Parse ``+HH:MM`` / ``-HH:MM`` into a fixed ``timezone``."""

    match = _OFFSET_RE.match(value or "")
    if not match:
        raise ValueError(f"invalid UTC offset: {value!r} (expected +HH:MM)")
    sign, hours, minutes = match.groups()
    if int(hours) > 14 or int(minutes) > 59:
        raise ValueError(f"UTC offset out of range: {value!r}")
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    if sign == "-":
        delta = -delta
    return timezone(delta)


def offset_label(value: str) -> str:
    """``+08:00`` -> ``UTC+08:00``."""

    parse_utc_offset(value)
    return f"UTC{value}"


def to_utc_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def from_ms(value_ms: int) -> datetime:
    return datetime.fromtimestamp(value_ms / 1000, tz=timezone.utc)


def iso(value_ms: int | None) -> str | None:
    """Render an instant as ISO 8601 UTC (``...Z``)."""

    if value_ms is None:
        return None
    return from_ms(value_ms).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> int:
    """Parse an ISO 8601 instant (``Z`` or offset) into UTC ms."""

    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone offset")
    return int(parsed.timestamp() * 1000)


def local_iso(value_ms: int, utc_offset: str) -> str:
    """Render an instant as wall-clock text in the global offset."""

    tz = parse_utc_offset(utc_offset)
    return from_ms(value_ms).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")


def local_date_bounds_ms(date_from: str | None, date_to: str | None, utc_offset: str) -> tuple[int | None, int | None]:
    """Convert inclusive ``YYYY-MM-DD`` date filters in the global offset to UTC ms."""

    tz = parse_utc_offset(utc_offset)

    def start(value: str) -> int:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=tz)
        return int(parsed.timestamp() * 1000)

    from_ms_value = start(date_from) if date_from else None
    to_ms_value = None
    if date_to:
        parsed = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=tz)
        to_ms_value = int((parsed + timedelta(days=1)).timestamp() * 1000) - 1
    return from_ms_value, to_ms_value
