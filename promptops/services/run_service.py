"""Run lifecycle services: create/manual/rerun/cancel/permission reply."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api import errors
from promptops.config import Settings
from promptops.domain.schedule import ScheduleSpec, schedule_summary
from promptops.domain.snapshots import build_run_snapshot, dump_snapshot
from promptops.enums import (
    CancelReason,
    RunStatus,
    TaskStatus,
    TERMINAL_RUN_STATUSES as TERMINAL_RUN_STATES,
    TraceKind,
    TraceStatus,
    TriggerSource,
)
from promptops.ids import new_id
from promptops.models import Endpoint, Run, Task
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.repositories import tasks as task_repo
from promptops.repositories import trace as trace_repo
from promptops.timeutil import iso

logger = logging.getLogger(__name__)


def _spec_for_task(task: Task) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=task.schedule_type,
        cron_expression=task.cron_expression,
        run_at=task.run_at,
        interval_seconds=task.interval_seconds,
        schedule_enabled=bool(task.schedule_enabled),
        next_run_at=task.next_run_at,
    )


async def create_run(
    session: AsyncSession,
    *,
    task: Task,
    endpoint: Endpoint,
    trigger_source: TriggerSource | str,
    scheduled_for: int | None,
    occurrence_key: str | None,
    status: RunStatus | str,
    settings: Settings,
    now_ms: int,
    rerun_of_run_id: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    details: dict[str, Any] | None = None,
) -> Run:
    """Insert a Run with a frozen configuration snapshot."""

    source = trigger_source.value if isinstance(trigger_source, TriggerSource) else str(trigger_source)
    status_value = status.value if isinstance(status, RunStatus) else str(status)
    snapshot = build_run_snapshot(
        task=task,
        endpoint=endpoint,
        trigger_source=source,
        scheduled_for=scheduled_for,
        utc_offset=settings.utc_offset,
    )
    run = Run(
        id=new_id("run"),
        task_id=task.id,
        trigger_source=source,
        status=status_value,
        occurrence_key=occurrence_key,
        scheduled_for=scheduled_for,
        created_at=now_ms,
        queued_at=now_ms if status_value == RunStatus.QUEUED.value else None,
        task_name_snapshot=task.name,
        endpoint_id=endpoint.id,
        endpoint_name_snapshot=endpoint.name,
        endpoint_url_snapshot=endpoint.base_url,
        endpoint_auth_type_snapshot=endpoint.auth_type,
        working_directory=task.working_directory,
        provider_id=task.provider_id,
        model_id=task.model_id,
        model_variant=task.model_variant,
        agent=task.agent,
        prompt=task.prompt,
        utc_offset=settings.utc_offset,
        schedule_summary=schedule_summary(_spec_for_task(task), settings.utc_offset),
        overlap_policy=task.overlap_policy,
        missed_policy=task.missed_policy,
        timeout_minutes=task.timeout_minutes,
        rerun_of_run_id=rerun_of_run_id,
        config_snapshot_json=dump_snapshot(snapshot),
        trace_integrity="none",
        trace_gap_count=0,
        updated_at=now_ms,
        finished_at=now_ms if status_value == RunStatus.SKIPPED.value else None,
        error_phase="scheduler" if status_value == RunStatus.SKIPPED.value else None,
        error_type=error_type if status_value == RunStatus.SKIPPED.value else None,
        error_message=error_message if status_value == RunStatus.SKIPPED.value else None,
    )
    session.add(run)
    await session.flush()
    await log_repo.append(
        session,
        run.id,
        at=now_ms,
        phase="created",
        message=f"Run created (source={source})",
        details=details,
    )
    if status_value == RunStatus.QUEUED.value:
        await log_repo.append(
            session, run.id, at=now_ms, phase="queued", message="Waiting for worker"
        )
    elif status_value == RunStatus.SKIPPED.value:
        await log_repo.append(
            session,
            run.id,
            at=now_ms,
            phase="skipped",
            message=f"Skipped: {error_message or error_type or 'policy'}",
            level="warn",
            details=details,
        )
    return run


async def _overlap_target(session: AsyncSession, task_id: str) -> Run | None:
    return await task_repo.has_pending_or_active_run(session, task_id)


async def manual_run(
    session: AsyncSession, task_id: str, *, settings: Settings, now_ms: int
) -> Run:
    task = await task_repo.get(session, task_id)
    if task is None:
        raise errors.not_found("Task not found")
    if task.status == TaskStatus.ARCHIVED.value:
        raise errors.forbidden("An archived task cannot be run manually")
    endpoint = await endpoint_repo.get(session, task.endpoint_id)
    if endpoint is None or not endpoint.enabled:
        raise errors.conflict("The task's endpoint is missing or disabled; cannot run")

    blocking = await _overlap_target(session, task.id)
    if blocking is not None and task.overlap_policy == "skip":
        return await create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=TriggerSource.MANUAL,
            scheduled_for=None,
            occurrence_key=None,
            status=RunStatus.SKIPPED,
            settings=settings,
            now_ms=now_ms,
            error_type="overlap",
            error_message=f"the previous run has not finished (run_id={blocking.id})",
            details={"blocking_run_id": blocking.id},
        )
    return await create_run(
        session,
        task=task,
        endpoint=endpoint,
        trigger_source=TriggerSource.MANUAL,
        scheduled_for=None,
        occurrence_key=None,
        status=RunStatus.QUEUED,
        settings=settings,
        now_ms=now_ms,
    )


async def rerun(
    session: AsyncSession,
    run_id: str,
    *,
    endpoint_id: str | None,
    settings: Settings,
    now_ms: int,
) -> Run:
    original = await run_repo.get(session, run_id)
    if original is None:
        raise errors.not_found("Run not found")
    if original.status not in {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.TIMEOUT.value,
        RunStatus.SKIPPED.value,
        RunStatus.UNKNOWN.value,
    }:
        raise errors.conflict("only finished runs can be rerun")

    endpoint: Endpoint | None = None
    adjusted = False
    if endpoint_id:
        endpoint = await endpoint_repo.get(session, endpoint_id)
        if endpoint is None or not endpoint.enabled:
            raise errors.validation_error("Select an available endpoint", {"endpoint_id": "unavailable"})
        adjusted = endpoint.id != original.endpoint_id
    elif original.endpoint_id:
        candidate = await endpoint_repo.get(session, original.endpoint_id)
        if candidate is not None and candidate.enabled:
            endpoint = candidate
    if endpoint is None:
        raise errors.conflict("The original endpoint was deleted or disabled; select an available endpoint")

    task = await task_repo.get(session, original.task_id)
    if task is None:
        raise errors.not_found("The original task no longer exists; cannot rerun")

    blocking = await _overlap_target(session, task.id)
    if blocking is not None and original.overlap_policy == "skip":
        return await _create_rerun_run(
            session,
            original=original,
            task=task,
            endpoint=endpoint,
            settings=settings,
            now_ms=now_ms,
            status=RunStatus.SKIPPED,
            error_type="overlap",
            error_message=f"the previous run has not finished (run_id={blocking.id})",
            adjusted=adjusted,
        )
    return await _create_rerun_run(
        session,
        original=original,
        task=task,
        endpoint=endpoint,
        settings=settings,
        now_ms=now_ms,
        status=RunStatus.QUEUED,
        error_type=None,
        error_message=None,
        adjusted=adjusted,
    )


async def _create_rerun_run(
    session: AsyncSession,
    *,
    original: Run,
    task: Task,
    endpoint: Endpoint,
    settings: Settings,
    now_ms: int,
    status: RunStatus,
    error_type: str | None,
    error_message: str | None,
    adjusted: bool,
) -> Run:
    snapshot = json.loads(original.config_snapshot_json or "{}")
    if not isinstance(snapshot, dict):
        snapshot = {}
    snapshot["endpoint"] = {
        "id": endpoint.id,
        "name": endpoint.name,
        "base_url": endpoint.base_url,
        "auth_type": endpoint.auth_type,
        "username": endpoint.auth_username if endpoint.auth_type == "basic" else None,
    }
    snapshot["trigger"] = {
        "source": TriggerSource.RERUN.value,
        "scheduled_for": None,
        "rerun_of_run_id": original.id,
    }
    if adjusted:
        snapshot["trigger"]["config_adjusted"] = True
        snapshot["trigger"]["adjustment_note"] = "The original endpoint was unavailable; the selected endpoint was used instead"
    run = Run(
        id=new_id("run"),
        task_id=original.task_id,
        trigger_source=TriggerSource.RERUN.value,
        status=status.value,
        occurrence_key=None,
        scheduled_for=None,
        created_at=now_ms,
        queued_at=now_ms if status == RunStatus.QUEUED else None,
        finished_at=now_ms if status == RunStatus.SKIPPED else None,
        task_name_snapshot=original.task_name_snapshot,
        endpoint_id=endpoint.id,
        endpoint_name_snapshot=endpoint.name,
        endpoint_url_snapshot=endpoint.base_url,
        endpoint_auth_type_snapshot=endpoint.auth_type,
        working_directory=original.working_directory,
        provider_id=original.provider_id,
        model_id=original.model_id,
        model_variant=original.model_variant,
        agent=original.agent,
        prompt=original.prompt,
        utc_offset=original.utc_offset,
        schedule_summary=original.schedule_summary,
        overlap_policy=original.overlap_policy,
        missed_policy=original.missed_policy,
        timeout_minutes=original.timeout_minutes,
        rerun_of_run_id=original.id,
        config_snapshot_json=dump_snapshot(snapshot),
        trace_integrity="none",
        trace_gap_count=0,
        error_phase="scheduler" if status == RunStatus.SKIPPED else None,
        error_type=error_type,
        error_message=error_message,
        updated_at=now_ms,
    )
    session.add(run)
    await session.flush()
    await log_repo.append(
        session,
        run.id,
        at=now_ms,
        phase="created",
        message=f"Run created (source=rerun, from={original.id})",
    )
    if status == RunStatus.QUEUED:
        await log_repo.append(
            session, run.id, at=now_ms, phase="queued", message="Waiting for worker"
        )
    else:
        await log_repo.append(
            session,
            run.id,
            at=now_ms,
            phase="skipped",
            message=f"Skipped: {error_message or 'overlap'}",
            level="warn",
        )
    return run


async def request_cancel(
    session: AsyncSession,
    run_id: str,
    *,
    registry: Any,
    now_ms: int,
) -> dict[str, object]:
    run = await run_repo.get(session, run_id)
    if run is None:
        raise errors.not_found("Run not found")
    if run.status in {item.value for item in TERMINAL_RUN_STATES}:
        raise errors.conflict("The run has already finished; it cannot be cancelled")

    if run.status == RunStatus.QUEUED.value:
        applied = await run_repo.transition(
            session,
            run.id,
            RunStatus.CANCELLED,
            expected=RunStatus.QUEUED,
            now=now_ms,
            cancel_requested_at=now_ms,
            cancel_confirmed_at=now_ms,
            cancel_reason=CancelReason.USER.value,
            finished_at=now_ms,
        )
        if applied:
            await log_repo.append(
                session, run.id, at=now_ms, phase="cancel_confirmed", message="Cancelled before start"
            )
        return {"status": RunStatus.CANCELLED.value, "message": "Cancelled (had not started)"}

    handle = registry.get(run.id) if registry is not None else None
    if handle is not None:
        handle.request_cancel()
    if run.status in (RunStatus.RUNNING.value, RunStatus.WAITING.value, RunStatus.SUBMITTING.value):
        applied = await run_repo.transition(
            session,
            run.id,
            RunStatus.CANCELLING,
            expected={RunStatus.RUNNING, RunStatus.WAITING, RunStatus.SUBMITTING},
            now=now_ms,
            cancel_requested_at=now_ms,
            cancel_reason=CancelReason.USER.value,
        )
        if applied:
            await log_repo.append(
                session, run.id, at=now_ms, phase="cancelling", message="Cancel requested (reason=user)"
            )
        return {
            "status": RunStatus.CANCELLING.value,
            "message": "Cancel requested; waiting for OpenCode to confirm the stop",
        }
    if run.status == RunStatus.PREPARING.value:
        if handle is None:
            applied = await run_repo.transition(
                session,
                run.id,
                RunStatus.CANCELLED,
                expected=RunStatus.PREPARING,
                now=now_ms,
                cancel_requested_at=now_ms,
                cancel_confirmed_at=now_ms,
                cancel_reason=CancelReason.USER.value,
                finished_at=now_ms,
            )
            if applied:
                await log_repo.append(
                    session,
                    run.id,
                    at=now_ms,
                    phase="cancel_confirmed",
                    message="Cancelled before prompt submission (no session)",
                )
            return {"status": RunStatus.CANCELLED.value, "message": "Cancelled (prompt had not been submitted)"}
        return {
            "status": RunStatus.PREPARING.value,
            "message": "Cancel requested; execution will stop at the next checkpoint",
        }
    if run.status == RunStatus.CANCELLING.value:
        return {"status": run.status, "message": "Cancellation is already in progress"}
    raise errors.conflict("the current state does not support cancellation")


async def reply_permission(
    session: AsyncSession,
    run_id: str,
    request_id: str,
    *,
    decision: str,
    message: str | None,
    runtime: Any,
    now_ms: int,
) -> None:
    run = await run_repo.get(session, run_id)
    if run is None:
        raise errors.not_found("Run not found")
    if run.status in {"completed", "failed", "cancelled", "timeout", "skipped", "unknown"}:
        raise errors.conflict("The run has already finished; permission requests cannot be answered")
    item = await trace_repo.get(session, run.id, TraceKind.PERMISSION.value, request_id)
    if item is None:
        raise errors.not_found("Permission request not found")
    if item.status not in (TraceStatus.PENDING.value, TraceStatus.INFO.value):
        raise errors.conflict("The permission request has already been handled")
    endpoint = await endpoint_repo.get(session, run.endpoint_id) if run.endpoint_id else None
    if endpoint is None:
        raise errors.conflict("The endpoint was deleted; cannot answer the permission request")
    if not run.opencode_session_id:
        raise errors.conflict("The run has not created an OpenCode session yet")
    client = runtime.make_client(endpoint)
    try:
        await client.reply_permission(run.opencode_session_id, request_id, decision, message)
    finally:
        await client.aclose()

    new_status = TraceStatus.REJECTED.value if decision == "reject" else TraceStatus.COMPLETED.value
    metadata = json.loads(item.metadata_json or "{}")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["decision"] = decision
    if message:
        metadata["message"] = message
    await trace_repo.upsert(
        session,
        run.id,
        kind=TraceKind.PERMISSION.value,
        external_id=request_id,
        now=now_ms,
        status=new_status,
        metadata=metadata,
    )
    await log_repo.append(
        session,
        run.id,
        at=now_ms,
        phase="permission_resolved",
        message=f"Permission {request_id} -> {decision}",
    )
    pending = await _pending_permissions(session, run.id)
    if not pending:
        await run_repo.transition(
            session,
            run.id,
            RunStatus.RUNNING,
            expected=RunStatus.WAITING,
            now=now_ms,
        )


async def _pending_permissions(session: AsyncSession, run_id: str) -> list:
    items = await trace_repo.list_for_run(session, run_id)
    return [
        item
        for item in items
        if item.kind == TraceKind.PERMISSION.value and item.status == TraceStatus.PENDING.value
    ]


async def pending_permissions(session: AsyncSession, run_id: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for item in await _pending_permissions(session, run_id):
        try:
            metadata = json.loads(item.metadata_json or "{}")
        except ValueError:
            metadata = {}
        result.append(
            {
                "request_id": item.external_id,
                "action": item.name,
                "status": item.status,
                "requested_at": iso(item.created_at),
                "input": json.loads(item.input_json) if item.input_json else None,
                "metadata": metadata,
            }
        )
    return result


__all__ = [
    "create_run",
    "manual_run",
    "rerun",
    "request_cancel",
    "reply_permission",
    "pending_permissions",
]
