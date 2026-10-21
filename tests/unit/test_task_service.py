from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from promptops.api import errors
from promptops.api.schemas import TaskCreate, TaskUpdate
from promptops.enums import TaskStatus
from promptops.services import task_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint

NOW = parse_iso("2026-10-19T00:00:00Z")


def payload(endpoint_id: str, **overrides) -> TaskCreate:
    body = {
        "name": "Monthly Rate Report",
        "tags": ["rates", "rates", " monthly "],
        "endpoint_id": endpoint_id,
        "working_directory": "/workspace/rates-report",
        "provider_id": "lps",
        "model_id": "Qwen/Qwen3.6-35B-A3B-FP8",
        "prompt": "Line 1\n  Line 2\n",
        "status": "enabled",
        "schedule_enabled": True,
        "schedule_type": "cron",
        "cron_expression": "0 9 1 * *",
        "overlap_policy": "queue",
        "missed_policy": "skip",
        "timeout_minutes": 60,
    }
    body.update(overrides)
    if isinstance(body.get("run_at"), str):
        body["run_at"] = datetime.fromisoformat(body["run_at"].replace("Z", "+00:00"))
    return TaskCreate(**body)


async def test_create_normalizes_tags_and_preserves_prompt(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session, payload(endpoint.id), settings=runtime.settings, now_ms=NOW
    )
    assert json.loads(task.tags_json) == ["rates", "monthly"]
    assert task.prompt == "Line 1\n  Line 2\n"
    assert task.next_run_at is not None
    assert task.next_run_at > NOW


async def test_disabled_endpoint_cannot_be_used_for_new_task(session, runtime):
    endpoint = await make_endpoint(session, enabled=False, is_default=False)
    with pytest.raises(errors.ApiError) as exc:
        await task_service.create_task(
            session, payload(endpoint.id), settings=runtime.settings, now_ms=NOW
        )
    assert exc.value.status == 422


async def test_invalid_cron_rejected(session, runtime):
    endpoint = await make_endpoint(session)
    with pytest.raises(errors.ApiError) as exc:
        await task_service.create_task(
            session,
            payload(endpoint.id, cron_expression="bad"),
            settings=runtime.settings,
            now_ms=NOW,
        )
    assert exc.value.details and "cron_expression" in exc.value.details


async def test_once_in_the_past_rejected(session, runtime):
    endpoint = await make_endpoint(session)
    past = datetime.fromtimestamp((NOW - 60_000) / 1000, tz=timezone.utc)
    with pytest.raises(errors.ApiError) as exc:
        await task_service.create_task(
            session,
            payload(endpoint.id, schedule_type="once", cron_expression=None, run_at=past),
            settings=runtime.settings,
            now_ms=NOW,
        )
    assert exc.value.status == 422


async def test_interval_starts_from_now(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session,
        payload(
            endpoint.id,
            schedule_type="interval",
            cron_expression=None,
            interval_seconds=1800,
        ),
        settings=runtime.settings,
        now_ms=NOW,
    )
    assert task.next_run_at == NOW + 1800_000


async def test_schedule_none_forces_disable(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session,
        payload(
            endpoint.id,
            schedule_type="none",
            cron_expression=None,
            schedule_enabled=True,
        ),
        settings=runtime.settings,
        now_ms=NOW,
    )
    assert task.schedule_enabled is False
    assert task.next_run_at is None


async def test_enable_rejects_expired_once(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session,
        payload(
            endpoint.id,
            schedule_type="once",
            cron_expression=None,
            run_at=datetime.fromtimestamp((NOW + 60_000) / 1000, tz=timezone.utc),
            status="disabled",
        ),
        settings=runtime.settings,
        now_ms=NOW,
    )
    task.run_at = NOW - 1
    await session.commit()
    with pytest.raises(errors.ApiError):
        await task_service.set_enabled(
            session, task.id, enabled=True, settings=runtime.settings, now_ms=NOW
        )


async def test_update_archived_task_is_rejected(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session, payload(endpoint.id), settings=runtime.settings, now_ms=NOW
    )
    await task_service.archive_task(session, task.id, now_ms=NOW)
    update = TaskUpdate(**payload(endpoint.id).model_dump())
    with pytest.raises(errors.ApiError) as exc:
        await task_service.update_task(
            session, task.id, update, settings=runtime.settings, now_ms=NOW
        )
    assert exc.value.status == 409


async def test_copy_is_disabled_and_does_not_schedule(session, runtime):
    endpoint = await make_endpoint(session)
    task = await task_service.create_task(
        session, payload(endpoint.id), settings=runtime.settings, now_ms=NOW
    )
    copied = await task_service.copy_task(session, task.id, now_ms=NOW)
    assert copied.name.startswith("Copy of ")
    assert copied.status == TaskStatus.DISABLED.value
    assert copied.schedule_enabled is False
    assert copied.next_run_at is None


async def test_preview_rejects_invalid_interval(runtime):
    from promptops.api.schemas import SchedulePreviewRequest

    with pytest.raises(errors.ApiError):
        task_service.preview_schedule(
            SchedulePreviewRequest(type="interval", interval_seconds=None),
            runtime.settings,
            NOW,
        )
