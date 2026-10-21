"""Pure scheduling functions: next occurrence, preview, catch-up.

All inputs/outputs are UTC epoch milliseconds.  Cron expressions are evaluated in
the single global fixed offset (default ``+08:00``); no IANA zone, no DST.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from croniter import CroniterBadCronError, croniter

from promptops.enums import ScheduleType
from promptops.timeutil import local_iso, parse_utc_offset

MAX_MISSED_ITERATIONS = 10_000


@dataclass(frozen=True)
class ScheduleSpec:
    """Minimal schedule input used by the pure functions."""

    schedule_type: str = ScheduleType.NONE.value
    cron_expression: str | None = None
    run_at: int | None = None
    interval_seconds: int | None = None
    schedule_enabled: bool = True
    next_run_at: int | None = None


def validate_cron(expression: str) -> str:
    """Validate a 5-field cron expression, returning it unchanged."""

    text = (expression or "").strip()
    if len(text.split()) != 5:
        raise ValueError("a cron expression must have 5 fields (minute hour day month weekday)")
    if not croniter.is_valid(text):
        raise ValueError("invalid cron expression")
    return text


def _cron_next(expression: str, after_ms: int, utc_offset: str) -> int:
    tz = parse_utc_offset(utc_offset)
    base = datetime.fromtimestamp(after_ms / 1000, tz=tz)
    try:
        iterator = croniter(expression, base)
        nxt = iterator.get_next(datetime)
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise ValueError(f"invalid cron expression: {expression}") from exc
    return int(nxt.timestamp() * 1000)


def _interval_next(spec: ScheduleSpec, after_ms: int) -> int | None:
    if not spec.interval_seconds:
        return None
    step = int(spec.interval_seconds) * 1000
    if step <= 0:
        return None
    base = spec.next_run_at if spec.next_run_at is not None else after_ms
    nxt = base + step
    if nxt <= after_ms:
        # Jump straight to the next future tick; never iterate per missed interval.
        nxt += ((after_ms - nxt) // step + 1) * step
    return nxt


def next_occurrence(spec: ScheduleSpec, after_ms: int, utc_offset: str) -> int | None:
    """First occurrence strictly after ``after_ms`` (``None`` when not schedulable)."""

    if not spec.schedule_enabled or spec.schedule_type == ScheduleType.NONE.value:
        return None
    if spec.schedule_type == ScheduleType.ONCE.value:
        if spec.run_at is not None and spec.run_at > after_ms:
            return spec.run_at
        return None
    if spec.schedule_type == ScheduleType.INTERVAL.value:
        return _interval_next(spec, after_ms)
    if spec.schedule_type == ScheduleType.CRON.value:
        if not spec.cron_expression:
            raise ValueError("a cron schedule requires a cron expression")
        return _cron_next(spec.cron_expression, after_ms, utc_offset)
    raise ValueError(f"unknown schedule type: {spec.schedule_type}")


def next_after(spec: ScheduleSpec, occurrence_ms: int, utc_offset: str) -> int | None:
    """Occurrence strictly after a known occurrence (used for catch-up)."""

    if spec.schedule_type == ScheduleType.ONCE.value:
        return None
    if spec.schedule_type == ScheduleType.INTERVAL.value:
        step = int(spec.interval_seconds or 0) * 1000
        return occurrence_ms + step if step > 0 else None
    if spec.schedule_type == ScheduleType.CRON.value:
        if not spec.cron_expression:
            raise ValueError("a cron schedule requires a cron expression")
        return _cron_next(spec.cron_expression, occurrence_ms, utc_offset)
    return None


def compute_latest_due(
    spec: ScheduleSpec, first_missed_ms: int, now_ms: int, utc_offset: str
) -> tuple[int, int]:
    """Fold every missed occurrence up to ``now_ms``.

    Returns ``(latest_due, missed_count)``.  Iteration is bounded; when the bound
    is hit the last computed due is returned (never a future instant).
    """

    latest = first_missed_ms
    count = 1
    cursor = first_missed_ms
    for _ in range(MAX_MISSED_ITERATIONS):
        nxt = next_after(spec, cursor, utc_offset)
        if nxt is None or nxt > now_ms:
            break
        latest = nxt
        count += 1
        cursor = nxt
    return latest, count


def preview_occurrences(
    spec: ScheduleSpec, count: int, utc_offset: str, now_ms: int
) -> list[dict[str, str]]:
    """Upcoming occurrences as ``{"utc": ISO, "local": "UTC+8 wall clock"}``."""

    from promptops.timeutil import iso

    if count < 1:
        return []
    occurrences: list[int] = []
    if spec.schedule_type == ScheduleType.NONE.value or not spec.schedule_enabled:
        return []
    if spec.schedule_type == ScheduleType.ONCE.value:
        if spec.run_at is not None and spec.run_at > now_ms:
            occurrences.append(spec.run_at)
    elif spec.schedule_type == ScheduleType.INTERVAL.value:
        step = int(spec.interval_seconds or 0) * 1000
        if step > 0:
            cursor = now_ms
            for _ in range(min(count, 10)):
                cursor += step
                occurrences.append(cursor)
    elif spec.schedule_type == ScheduleType.CRON.value:
        cursor = now_ms
        for _ in range(min(count, 10)):
            nxt = _cron_next(spec.cron_expression or "", cursor, utc_offset)
            occurrences.append(nxt)
            cursor = nxt
    return [
        {"utc": iso(item) or "", "local": local_iso(item, utc_offset)} for item in occurrences
    ]


def schedule_summary(spec: ScheduleSpec, utc_offset: str) -> str:
    """Human readable schedule summary stored on every Run."""

    label = f"UTC{utc_offset}"
    if not spec.schedule_enabled or spec.schedule_type == ScheduleType.NONE.value:
        return "Manual only"
    if spec.schedule_type == ScheduleType.ONCE.value and spec.run_at:
        return f"Once at {local_iso(spec.run_at, utc_offset)} ({label})"
    if spec.schedule_type == ScheduleType.INTERVAL.value:
        return f"Every {spec.interval_seconds}s ({label})"
    if spec.schedule_type == ScheduleType.CRON.value:
        return f"Cron {spec.cron_expression} ({label})"
    return "Unknown schedule"
