import pytest

from promptops.domain.schedule import (
    ScheduleSpec,
    compute_latest_due,
    next_occurrence,
    preview_occurrences,
    schedule_summary,
    validate_cron,
)
from promptops.timeutil import local_iso, parse_iso, parse_utc_offset

OFFSET = "+08:00"
NOW = parse_iso("2026-10-19T00:00:00Z")


def test_fixed_offset_parsing():
    tz = parse_utc_offset("+08:00")
    assert tz.utcoffset(None).total_seconds() == 8 * 3600
    with pytest.raises(ValueError):
        parse_utc_offset("08:00")


def test_cron_next_uses_utc8_wall_clock():
    spec = ScheduleSpec(schedule_type="cron", cron_expression="0 9 * * *")
    occurrence = next_occurrence(spec, NOW, OFFSET)
    assert local_iso(occurrence, OFFSET) == "2026-10-19 09:00:00"


def test_cron_monthly():
    spec = ScheduleSpec(schedule_type="cron", cron_expression="0 9 1 * *")
    occurrence = next_occurrence(spec, NOW, OFFSET)
    assert local_iso(occurrence, OFFSET) == "2026-11-01 09:00:00"


def test_interval_next_occurrence():
    spec = ScheduleSpec(
        schedule_type="interval", interval_seconds=1800, next_run_at=NOW
    )
    assert next_occurrence(spec, NOW, OFFSET) == NOW + 1800_000
    later = NOW + 4 * 3600_000
    nxt = next_occurrence(spec, later, OFFSET)
    assert nxt > later
    assert nxt - NOW == 9 * 1800_000


def test_once_before_and_after():
    spec = ScheduleSpec(schedule_type="once", run_at=NOW + 60_000)
    assert next_occurrence(spec, NOW, OFFSET) == NOW + 60_000
    assert next_occurrence(spec, NOW + 120_000, OFFSET) is None


def test_disabled_and_none_have_no_occurrence():
    assert next_occurrence(ScheduleSpec(schedule_type="none"), NOW, OFFSET) is None
    assert (
        next_occurrence(
            ScheduleSpec(schedule_type="cron", cron_expression="0 9 * * *", schedule_enabled=False),
            NOW,
            OFFSET,
        )
        is None
    )


def test_preview_returns_utc_and_local():
    spec = ScheduleSpec(schedule_type="cron", cron_expression="0 9 * * *")
    occurrences = preview_occurrences(spec, 5, OFFSET, NOW)
    assert len(occurrences) == 5
    assert occurrences[0]["local"] == "2026-10-19 09:00:00"
    assert occurrences[0]["utc"] == "2026-10-19T01:00:00.000Z"


def test_preview_none_returns_empty():
    assert preview_occurrences(ScheduleSpec(schedule_type="none"), 5, OFFSET, NOW) == []


def test_invalid_cron_rejected():
    with pytest.raises(ValueError):
        validate_cron("not a cron")
    with pytest.raises(ValueError):
        validate_cron("0 9 * *")  # only four fields
    with pytest.raises(ValueError):
        validate_cron("61 9 * * *")


def test_missed_folding_counts_and_latest():
    spec = ScheduleSpec(schedule_type="cron", cron_expression="0 9 * * *")
    first_missed = parse_iso("2026-10-15T01:00:00Z")
    now = parse_iso("2026-10-19T00:00:00Z")
    latest, count = compute_latest_due(spec, first_missed, now, OFFSET)
    assert count == 4
    assert local_iso(latest, OFFSET) == "2026-10-18 09:00:00"


def test_summary_labels_offset():
    spec = ScheduleSpec(schedule_type="cron", cron_expression="0 9 1 * *")
    assert schedule_summary(spec, OFFSET) == "Cron 0 9 1 * * (UTC+08:00)"
    assert schedule_summary(ScheduleSpec(), OFFSET) == "Manual only"
