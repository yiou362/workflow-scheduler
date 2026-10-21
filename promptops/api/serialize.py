"""ORM -> JSON serializers.

Passwords and ciphertext are never included.  Times are ISO 8601 UTC; the UI
renders them in the global UTC offset (Run snapshots carry their own offset).
"""

from __future__ import annotations

import json
from typing import Any

from promptops.models import Endpoint, Run, RunLog, Task, TraceItem
from promptops.timeutil import iso


def endpoint_dict(endpoint: Endpoint, *, task_count: int = 0) -> dict[str, Any]:
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "description": endpoint.description,
        "base_url": endpoint.base_url,
        "auth_type": endpoint.auth_type,
        "auth_username": endpoint.auth_username,
        "has_password": bool(endpoint.secret_ciphertext),
        "is_default": bool(endpoint.is_default),
        "enabled": bool(endpoint.enabled),
        "task_count": task_count,
        "last_test_at": iso(endpoint.last_test_at),
        "last_test_result": endpoint.last_test_result,
        "last_test_message": endpoint.last_test_message,
        "last_test_version": endpoint.last_test_version,
        "created_at": iso(endpoint.created_at),
        "updated_at": iso(endpoint.updated_at),
    }


def task_dict(
    task: Task, *, last_run: Run | None = None, endpoint_name: str | None = None
) -> dict[str, Any]:
    try:
        tags = json.loads(task.tags_json or "[]")
    except ValueError:
        tags = []
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description,
        "tags": tags if isinstance(tags, list) else [],
        "endpoint_id": task.endpoint_id,
        "endpoint_name": endpoint_name,
        "working_directory": task.working_directory,
        "provider_id": task.provider_id,
        "model_id": task.model_id,
        "model_variant": task.model_variant,
        "agent": task.agent,
        "prompt": task.prompt,
        "status": task.status,
        "schedule_enabled": bool(task.schedule_enabled),
        "schedule_type": task.schedule_type,
        "cron_expression": task.cron_expression,
        "run_at": iso(task.run_at),
        "interval_seconds": task.interval_seconds,
        "overlap_policy": task.overlap_policy,
        "missed_policy": task.missed_policy,
        "timeout_minutes": task.timeout_minutes,
        "next_run_at": iso(task.next_run_at),
        "schedule_summary": _schedule_summary(task),
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
        "archived_at": iso(task.archived_at),
        "last_run": run_brief(last_run) if last_run else None,
    }


def _schedule_summary(task: Task) -> str:
    if not task.schedule_enabled or task.schedule_type == "none":
        return "Manual only"
    if task.schedule_type == "cron":
        return f"Cron {task.cron_expression}"
    if task.schedule_type == "once":
        return f"Once at {iso(task.run_at)}"
    if task.schedule_type == "interval":
        return f"Every {task.interval_seconds}s"
    return "Unknown schedule"


def run_brief(run: Run | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "trigger_source": run.trigger_source,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "created_at": iso(run.created_at),
        "duration_ms": (
            run.finished_at - run.started_at
            if run.finished_at is not None and run.started_at is not None
            else None
        ),
    }


def run_dict(run: Run) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    try:
        parsed = json.loads(run.config_snapshot_json or "{}")
        if isinstance(parsed, dict):
            snapshot = parsed
    except ValueError:
        snapshot = {}
    return {
        "id": run.id,
        "task_id": run.task_id,
        "task_name": run.task_name_snapshot,
        "status": run.status,
        "trigger_source": run.trigger_source,
        "scheduled_for": iso(run.scheduled_for),
        "created_at": iso(run.created_at),
        "queued_at": iso(run.queued_at),
        "started_at": iso(run.started_at),
        "submitting_at": iso(run.submitting_at),
        "running_at": iso(run.running_at),
        "finished_at": iso(run.finished_at),
        "deadline_at": iso(run.deadline_at),
        "cancel_requested_at": iso(run.cancel_requested_at),
        "cancel_confirmed_at": iso(run.cancel_confirmed_at),
        "cancel_reason": run.cancel_reason,
        "duration_ms": (
            run.finished_at - run.started_at
            if run.finished_at is not None and run.started_at is not None
            else None
        ),
        "queue_wait_ms": (
            run.started_at - run.queued_at
            if run.started_at is not None and run.queued_at is not None
            else None
        ),
        "endpoint": {
            "id": run.endpoint_id,
            "name": run.endpoint_name_snapshot,
            "base_url": run.endpoint_url_snapshot,
            "auth_type": run.endpoint_auth_type_snapshot,
        },
        "working_directory": run.working_directory,
        "provider_id": run.provider_id,
        "model_id": run.model_id,
        "model_variant": run.model_variant,
        "agent": run.agent,
        "prompt": run.prompt,
        "utc_offset": run.utc_offset,
        "schedule_summary": run.schedule_summary,
        "overlap_policy": run.overlap_policy,
        "missed_policy": run.missed_policy,
        "timeout_minutes": run.timeout_minutes,
        "opencode_session_id": run.opencode_session_id,
        "opencode_session_title": run.opencode_session_title,
        "final_response": run.final_response,
        "final_response_truncated": bool(run.final_response_truncated),
        "error_phase": run.error_phase,
        "error_type": run.error_type,
        "error_message": run.error_message,
        "trace_integrity": run.trace_integrity,
        "trace_gap_count": run.trace_gap_count,
        "usage": {
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "reasoning_tokens": run.reasoning_tokens,
            "cache_read_tokens": run.cache_read_tokens,
            "cache_write_tokens": run.cache_write_tokens,
            "cost_usd": run.cost_usd,
        },
        "rerun_of_run_id": run.rerun_of_run_id,
        "config_snapshot": snapshot,
    }


def run_list_item(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "task_name": run.task_name_snapshot,
        "status": run.status,
        "trigger_source": run.trigger_source,
        "endpoint_id": run.endpoint_id,
        "endpoint_name": run.endpoint_name_snapshot,
        "model_id": run.model_id,
        "created_at": iso(run.created_at),
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
        "duration_ms": (
            run.finished_at - run.started_at
            if run.finished_at is not None and run.started_at is not None
            else None
        ),
        "trace_integrity": run.trace_integrity,
        "utc_offset": run.utc_offset,
        "error_type": run.error_type,
    }


def trace_dict(item: TraceItem) -> dict[str, Any]:
    def _json(value: str | None) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except ValueError:
            return value

    return {
        "id": item.id,
        "kind": item.kind,
        "external_id": item.external_id,
        "parent_external_id": item.parent_external_id,
        "name": item.name,
        "status": item.status,
        "sequence": item.sequence,
        "started_at": iso(item.started_at),
        "ended_at": iso(item.ended_at),
        "duration_ms": item.duration_ms,
        "input": _json(item.input_json),
        "output": item.output_text,
        "error": item.error_text,
        "metadata": _json(item.metadata_json),
    }


def log_dict(entry: RunLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "at": iso(entry.at),
        "level": entry.level,
        "phase": entry.phase,
        "message": entry.message,
        "details": json.loads(entry.details_json) if entry.details_json else None,
    }
