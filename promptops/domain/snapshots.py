"""Run configuration snapshot construction.

The snapshot is the authoritative record of what a Run executed.  It is written
once at Run creation and never updated.  Passwords are never part of it.
"""

from __future__ import annotations

import json
from typing import Any

from promptops.domain.schedule import ScheduleSpec, schedule_summary


def _schedule_spec(task: Any) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=task.schedule_type,
        cron_expression=task.cron_expression,
        run_at=task.run_at,
        interval_seconds=task.interval_seconds,
        schedule_enabled=bool(task.schedule_enabled),
        next_run_at=task.next_run_at,
    )


def build_run_snapshot(
    *,
    task: Any,
    endpoint: Any,
    trigger_source: str,
    scheduled_for: int | None,
    utc_offset: str,
    adjusted_note: str | None = None,
) -> dict[str, Any]:
    """Build the immutable ``config_snapshot_json`` payload for a new Run."""

    spec = _schedule_spec(task)
    snapshot: dict[str, Any] = {
        "task": {
            "id": task.id,
            "name": task.name,
            "description": task.description,
            "tags": json.loads(task.tags_json or "[]"),
        },
        "endpoint": {
            "id": endpoint.id,
            "name": endpoint.name,
            "base_url": endpoint.base_url,
            "auth_type": endpoint.auth_type,
            "username": endpoint.auth_username if endpoint.auth_type == "basic" else None,
        },
        "execution": {
            "working_directory": task.working_directory,
            "provider_id": task.provider_id,
            "model_id": task.model_id,
            "model_variant": task.model_variant,
            "agent": task.agent,
        },
        "prompt": task.prompt,
        "schedule": {
            "type": task.schedule_type,
            "cron": task.cron_expression,
            "run_at": task.run_at,
            "interval_seconds": task.interval_seconds,
            "utc_offset": utc_offset,
            "summary": schedule_summary(spec, utc_offset),
        },
        "policy": {
            "overlap": task.overlap_policy,
            "missed": task.missed_policy,
            "timeout_minutes": task.timeout_minutes,
        },
        "trigger": {"source": trigger_source, "scheduled_for": scheduled_for},
    }
    if adjusted_note:
        snapshot["trigger"]["config_adjusted"] = True
        snapshot["trigger"]["adjustment_note"] = adjusted_note
    return snapshot


def dump_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
