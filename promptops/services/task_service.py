"""Task management: validation, scheduling fields, lifecycle actions, preview."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api import errors
from promptops.api.schemas import SchedulePreviewRequest, TaskCreate, TaskUpdate
from promptops.config import Settings
from promptops.domain.schedule import (
    ScheduleSpec,
    next_occurrence,
    preview_occurrences,
    validate_cron,
)
from promptops.enums import MissedPolicy, OverlapPolicy, ScheduleType, TaskStatus
from promptops.ids import new_id
from promptops.models import Task
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import tasks as task_repo
from promptops.timeutil import iso, offset_label, parse_iso

logger = logging.getLogger(__name__)


def _normalize_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in tags:
        value = (item or "").strip()
        if not value:
            continue
        if len(value) > 32:
            raise errors.validation_error("A tag cannot exceed 32 characters", {"tags": "tag too long"})
        if value not in seen:
            seen.add(value)
            result.append(value)
    if len(result) > 20:
        raise errors.validation_error("At most 20 tags are allowed", {"tags": "too many tags"})
    return result


def _ms(value) -> int | None:  # noqa: ANN001 - pydantic datetime
    if value is None:
        return None
    return int(value.timestamp() * 1000)


async def get_or_404(session: AsyncSession, task_id: str) -> Task:
    task = await task_repo.get(session, task_id)
    if task is None:
        raise errors.not_found("Task not found")
    return task


def _schedule_spec(task: Task) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=task.schedule_type,
        cron_expression=task.cron_expression,
        run_at=task.run_at,
        interval_seconds=task.interval_seconds,
        schedule_enabled=bool(task.schedule_enabled),
        next_run_at=task.next_run_at,
    )


def compute_next_run_at(task: Task, now_ms: int, utc_offset: str) -> int | None:
    if task.status != TaskStatus.ENABLED.value:
        return None
    if not task.schedule_enabled or task.schedule_type == ScheduleType.NONE.value:
        return None
    if task.schedule_type == ScheduleType.ONCE.value:
        return task.run_at if task.run_at and task.run_at > now_ms else None
    if task.schedule_type == ScheduleType.INTERVAL.value:
        if not task.interval_seconds or task.interval_seconds < 60:
            return None
        return now_ms + task.interval_seconds * 1000
    return next_occurrence(_schedule_spec(task), now_ms, utc_offset)


def _validate_prompt(prompt: str) -> str:
    if not (prompt or "").strip():
        raise errors.validation_error("Prompt cannot be empty", {"prompt": "cannot be empty"})
    return prompt


def _validate_schedule_fields(
    *,
    schedule_enabled: bool,
    schedule_type: str,
    cron_expression: str | None,
    run_at_ms: int | None,
    interval_seconds: int | None,
    now_ms: int,
) -> None:
    if schedule_type == ScheduleType.NONE.value:
        return
    if not schedule_enabled:
        return
    if schedule_type == ScheduleType.CRON.value:
        if not cron_expression:
            raise errors.validation_error("A cron schedule requires an expression", {"cron_expression": "cannot be empty"})
        try:
            validate_cron(cron_expression)
        except ValueError as exc:
            raise errors.validation_error(str(exc), {"cron_expression": str(exc)}) from exc
    elif schedule_type == ScheduleType.ONCE.value:
        if run_at_ms is None:
            raise errors.validation_error("A one-time schedule requires a run time", {"run_at": "cannot be empty"})
        if run_at_ms <= now_ms:
            raise errors.validation_error(
                "The one-time run time must be in the future", {"run_at": "time already passed"}
            )
    elif schedule_type == ScheduleType.INTERVAL.value:
        if not interval_seconds or interval_seconds < 60:
            raise errors.validation_error(
                "The fixed interval cannot be shorter than 60 seconds", {"interval_seconds": "minimum is 60 seconds"}
            )


def _apply_schedule(task: Task, payload: TaskCreate | TaskUpdate, now_ms: int, utc_offset: str) -> None:
    schedule_type = payload.schedule_type
    schedule_enabled = payload.schedule_enabled
    if schedule_type == ScheduleType.NONE.value:
        schedule_enabled = False
    run_at_ms = _ms(payload.run_at)
    _validate_schedule_fields(
        schedule_enabled=schedule_enabled,
        schedule_type=schedule_type,
        cron_expression=payload.cron_expression,
        run_at_ms=run_at_ms,
        interval_seconds=payload.interval_seconds,
        now_ms=now_ms,
    )
    task.schedule_type = schedule_type
    task.schedule_enabled = schedule_enabled
    task.cron_expression = payload.cron_expression if schedule_type == "cron" else None
    task.run_at = run_at_ms if schedule_type == "once" else None
    task.interval_seconds = payload.interval_seconds if schedule_type == "interval" else None
    task.next_run_at = compute_next_run_at(task, now_ms, utc_offset)


async def create_task(
    session: AsyncSession,
    payload: TaskCreate,
    *,
    settings: Settings,
    now_ms: int,
) -> Task:
    endpoint = await endpoint_repo.get(session, payload.endpoint_id)
    if endpoint is None:
        raise errors.validation_error("Endpoint not found", {"endpoint_id": "not found"})
    if not endpoint.enabled:
        raise errors.validation_error("A disabled endpoint cannot be used", {"endpoint_id": "disabled"})
    prompt = _validate_prompt(payload.prompt)
    task = Task(
        id=new_id("task"),
        name=payload.name.strip(),
        description=payload.description or None,
        tags_json=json.dumps(_normalize_tags(payload.tags), ensure_ascii=False),
        endpoint_id=endpoint.id,
        working_directory=payload.working_directory,
        provider_id=payload.provider_id.strip(),
        model_id=payload.model_id.strip(),
        model_variant=(payload.model_variant or None),
        agent=(payload.agent or None),
        prompt=prompt,
        status=payload.status,
        schedule_type=payload.schedule_type,
        schedule_enabled=False,
        overlap_policy=payload.overlap_policy,
        missed_policy=payload.missed_policy,
        timeout_minutes=payload.timeout_minutes,
        created_at=now_ms,
        updated_at=now_ms,
    )
    _apply_schedule(task, payload, now_ms, settings.utc_offset)
    session.add(task)
    await session.flush()
    return task


async def update_task(
    session: AsyncSession,
    task_id: str,
    payload: TaskUpdate,
    *,
    settings: Settings,
    now_ms: int,
) -> Task:
    task = await get_or_404(session, task_id)
    if task.status == TaskStatus.ARCHIVED.value:
        raise errors.conflict("An archived task cannot be edited; restore it first")
    endpoint = await endpoint_repo.get(session, payload.endpoint_id)
    if endpoint is None:
        raise errors.validation_error("Endpoint not found", {"endpoint_id": "not found"})
    if not endpoint.enabled and endpoint.id != task.endpoint_id:
        raise errors.validation_error("A disabled endpoint cannot be used", {"endpoint_id": "disabled"})

    task.name = payload.name.strip()
    task.description = payload.description or None
    task.tags_json = json.dumps(_normalize_tags(payload.tags), ensure_ascii=False)
    task.endpoint_id = endpoint.id
    task.working_directory = payload.working_directory
    task.provider_id = payload.provider_id.strip()
    task.model_id = payload.model_id.strip()
    task.model_variant = payload.model_variant or None
    task.agent = payload.agent or None
    task.prompt = _validate_prompt(payload.prompt)
    task.status = payload.status
    task.overlap_policy = payload.overlap_policy
    task.missed_policy = payload.missed_policy
    task.timeout_minutes = payload.timeout_minutes
    task.updated_at = now_ms
    if task.status == TaskStatus.ARCHIVED.value:
        task.archived_at = task.archived_at or now_ms
    else:
        task.archived_at = None
    _apply_schedule(task, payload, now_ms, settings.utc_offset)
    await session.flush()
    return task


async def set_enabled(
    session: AsyncSession, task_id: str, *, enabled: bool, settings: Settings, now_ms: int
) -> Task:
    task = await get_or_404(session, task_id)
    if task.status == TaskStatus.ARCHIVED.value:
        raise errors.conflict("An archived task cannot be enabled; restore it first")
    if enabled:
        if task.schedule_type == ScheduleType.ONCE.value:
            if not task.run_at or task.run_at <= now_ms:
                raise errors.conflict("The one-time run time has passed; update the time first")
        task.status = TaskStatus.ENABLED.value
        task.next_run_at = compute_next_run_at(task, now_ms, settings.utc_offset)
    else:
        task.status = TaskStatus.DISABLED.value
        task.next_run_at = None
    task.updated_at = now_ms
    await session.flush()
    return task


async def archive_task(session: AsyncSession, task_id: str, *, now_ms: int) -> Task:
    task = await get_or_404(session, task_id)
    task.status = TaskStatus.ARCHIVED.value
    task.schedule_enabled = False
    task.next_run_at = None
    task.archived_at = now_ms
    task.updated_at = now_ms
    await session.flush()
    return task


async def restore_task(session: AsyncSession, task_id: str, *, settings: Settings, now_ms: int) -> Task:
    task = await get_or_404(session, task_id)
    task.status = TaskStatus.DISABLED.value
    task.archived_at = None
    task.next_run_at = None
    task.updated_at = now_ms
    await session.flush()
    return task


async def copy_task(session: AsyncSession, task_id: str, *, now_ms: int) -> Task:
    source = await get_or_404(session, task_id)
    base_name = f"Copy of {source.name}"
    name = base_name
    suffix = 2
    while True:
        existing = await session.scalar(select(Task.id).where(Task.name == name))
        if existing is None:
            break
        name = f"{base_name} ({suffix})"
        suffix += 1
    task = Task(
        id=new_id("task"),
        name=name,
        description=source.description,
        tags_json=source.tags_json,
        endpoint_id=source.endpoint_id,
        working_directory=source.working_directory,
        provider_id=source.provider_id,
        model_id=source.model_id,
        model_variant=source.model_variant,
        agent=source.agent,
        prompt=source.prompt,
        status=TaskStatus.DISABLED.value,
        schedule_enabled=False,
        schedule_type=source.schedule_type,
        cron_expression=source.cron_expression,
        run_at=source.run_at,
        interval_seconds=source.interval_seconds,
        overlap_policy=source.overlap_policy,
        missed_policy=source.missed_policy,
        timeout_minutes=source.timeout_minutes,
        next_run_at=None,
        created_at=now_ms,
        updated_at=now_ms,
    )
    session.add(task)
    await session.flush()
    return task


def preview_schedule(
    payload: SchedulePreviewRequest, settings: Settings, now_ms: int
) -> dict[str, object]:
    spec = ScheduleSpec(
        schedule_type=payload.type,
        cron_expression=payload.cron,
        run_at=_ms(payload.run_at),
        interval_seconds=payload.interval_seconds,
        schedule_enabled=payload.type != "none",
    )
    if payload.type == "cron":
        if not payload.cron:
            raise errors.validation_error("A cron schedule requires an expression", {"cron": "cannot be empty"})
        try:
            validate_cron(payload.cron)
        except ValueError as exc:
            raise errors.validation_error(str(exc), {"cron": str(exc)}) from exc
    if payload.type == "once" and spec.run_at is None:
        raise errors.validation_error("A one-time schedule requires a run time", {"run_at": "cannot be empty"})
    if payload.type == "interval" and (payload.interval_seconds or 0) < 60:
        raise errors.validation_error("The fixed interval cannot be shorter than 60 seconds", {"interval_seconds": "minimum is 60 seconds"})
    occurrences = preview_occurrences(spec, payload.count, settings.utc_offset, now_ms)
    return {
        "occurrences": occurrences,
        "utc_offset": settings.utc_offset,
        "utc_offset_label": offset_label(settings.utc_offset),
    }
