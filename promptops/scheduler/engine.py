"""Scheduler engine: a 1s tick that turns due Tasks into Runs (exactly once)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from promptops.domain.schedule import ScheduleSpec, compute_latest_due, next_occurrence
from promptops.enums import RunStatus, ScheduleType, TaskStatus, TriggerSource
from promptops.models import Run, Task
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import tasks as task_repo
from promptops.services import run_service

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)


class SchedulerEngine:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.tick_seconds = runtime.settings.scheduler_tick_seconds
        self.missed_grace_ms = runtime.settings.missed_grace_seconds * 1000
        self._task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="promptops-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.tick_seconds)
                await self.tick(self.runtime.clock.now_ms())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - tick must not kill the loop
                logger.exception("scheduler tick failed")

    async def tick(self, now_ms: int) -> None:
        async with self._lock:
            async with self.runtime.session_factory() as session:
                due_ids = await task_repo.tasks_due(session, now_ms)
            for task_id in due_ids:
                try:
                    await self._process_task(task_id, now_ms)
                except Exception:  # noqa: BLE001
                    logger.exception("scheduler failed for task %s", task_id)

    async def _process_task(self, task_id: str, now_ms: int) -> None:
        async with self.runtime.session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None or not _schedulable(task) or task.next_run_at is None:
                return
            occurrence = int(task.next_run_at)
            late = now_ms - occurrence
            try:
                if late > self.missed_grace_ms:
                    await self._handle_missed(session, task, occurrence, now_ms)
                else:
                    await self._handle_due(session, task, occurrence, now_ms)
            except Exception:
                await session.rollback()
                raise
            await session.commit()

    async def _handle_due(
        self, session, task: Task, occurrence: int, now_ms: int
    ) -> None:  # noqa: ANN001
        endpoint = await endpoint_repo.get(session, task.endpoint_id)
        if endpoint is None or not endpoint.enabled:
            await self._create_skipped(
                session, task, occurrence, now_ms, "endpoint_disabled", "Endpoint is disabled"
            )
            await self._advance(session, task, now_ms)
            return

        blocking = await task_repo.has_pending_or_active_run(session, task.id)
        if blocking is not None and task.overlap_policy == "skip":
            await self._create_skipped(
                session,
                task,
                occurrence,
                now_ms,
                "overlap",
                f"the previous run has not finished (run_id={blocking.id})",
                details={"blocking_run_id": blocking.id},
            )
        elif await self._occurrence_exists(session, task.id, occurrence):
            pass
        else:
            await run_service.create_run(
                session,
                task=task,
                endpoint=endpoint,
                trigger_source=TriggerSource.SCHEDULED,
                scheduled_for=occurrence,
                occurrence_key=f"occ:{occurrence}",
                status=RunStatus.QUEUED,
                settings=self.runtime.settings,
                now_ms=now_ms,
            )
        await self._advance(session, task, now_ms)

    async def _handle_missed(
        self, session, task: Task, first_missed: int, now_ms: int
    ) -> None:  # noqa: ANN001
        spec = _spec(task)
        latest_due, missed_count = compute_latest_due(
            spec, first_missed, now_ms, self.runtime.settings.utc_offset
        )
        endpoint = await endpoint_repo.get(session, task.endpoint_id)
        if endpoint is None or not endpoint.enabled:
            await self._create_skipped(
                session,
                task,
                latest_due,
                now_ms,
                "endpoint_disabled",
                "Endpoint is disabled; the missed slot was not executed",
                source=TriggerSource.RECOVERY,
                details={"missed_count": missed_count},
            )
        elif task.missed_policy == "skip":
            await self._create_skipped(
                session,
                task,
                latest_due,
                now_ms,
                "missed_schedule",
                f"missed {missed_count} scheduled runs; not caught up per policy",
                source=TriggerSource.RECOVERY,
                details={"missed_count": missed_count},
            )
        elif await self._occurrence_exists(session, task.id, latest_due):
            pass
        elif await task_repo.has_pending_or_active_run(session, task.id) and task.overlap_policy == "skip":
            await self._create_skipped(
                session,
                task,
                latest_due,
                now_ms,
                "overlap",
                "the previous run had not finished when the recovery catch-up fired",
                source=TriggerSource.RECOVERY,
            )
        else:
            await run_service.create_run(
                session,
                task=task,
                endpoint=endpoint,
                trigger_source=TriggerSource.RECOVERY,
                scheduled_for=latest_due,
                occurrence_key=f"occ:{latest_due}",
                status=RunStatus.QUEUED,
                settings=self.runtime.settings,
                now_ms=now_ms,
                details={"missed_count": missed_count},
            )
        await self._advance(session, task, now_ms)

    async def _create_skipped(
        self,
        session,
        task: Task,
        occurrence: int,
        now_ms: int,
        error_type: str,
        message: str,
        *,
        source: TriggerSource = TriggerSource.SCHEDULED,
        details: dict | None = None,
    ) -> None:  # noqa: ANN001
        if await self._occurrence_exists(session, task.id, occurrence):
            return
        endpoint = await endpoint_repo.get(session, task.endpoint_id)
        if endpoint is None:
            return
        await run_service.create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=source,
            scheduled_for=occurrence,
            occurrence_key=f"occ:{occurrence}",
            status=RunStatus.SKIPPED,
            settings=self.runtime.settings,
            now_ms=now_ms,
            error_type=error_type,
            error_message=message,
            details=details,
        )

    async def _occurrence_exists(self, session, task_id: str, occurrence: int) -> bool:  # noqa: ANN001
        found = await session.scalar(
            select(Run.id).where(
                Run.task_id == task_id, Run.occurrence_key == f"occ:{occurrence}"
            )
        )
        return found is not None

    async def _advance(self, session, task: Task, now_ms: int) -> None:  # noqa: ANN001
        if task.schedule_type == ScheduleType.ONCE.value:
            task.schedule_enabled = False
            task.next_run_at = None
        else:
            task.next_run_at = next_occurrence(
                _spec(task), now_ms, self.runtime.settings.utc_offset
            )
        task.updated_at = now_ms
        await session.flush()


def _spec(task: Task) -> ScheduleSpec:
    return ScheduleSpec(
        schedule_type=task.schedule_type,
        cron_expression=task.cron_expression,
        run_at=task.run_at,
        interval_seconds=task.interval_seconds,
        schedule_enabled=bool(task.schedule_enabled),
        next_run_at=task.next_run_at,
    )


def _schedulable(task: Task) -> bool:
    return (
        task.status == TaskStatus.ENABLED.value
        and bool(task.schedule_enabled)
        and task.schedule_type != ScheduleType.NONE.value
    )
