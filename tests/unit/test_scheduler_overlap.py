from __future__ import annotations

from sqlalchemy import select

from promptops.enums import RunStatus, TriggerSource
from promptops.models import Run
from promptops.scheduler.engine import SchedulerEngine
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def _active_run(session, runtime, task, endpoint):
    run = await run_service.create_run(
        session,
        task=task,
        endpoint=endpoint,
        trigger_source=TriggerSource.MANUAL,
        scheduled_for=None,
        occurrence_key=None,
        status=RunStatus.RUNNING,
        settings=runtime.settings,
        now_ms=NOW,
    )
    await session.commit()
    return run


async def test_overlap_queue_creates_queued_run(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
            overlap_policy="queue",
        )
        await _active_run(session, runtime, task, endpoint)
        task_id = task.id

    await SchedulerEngine(runtime).tick(NOW + 100)
    async with session_factory() as session:
        runs = list(
            (await session.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.created_at))).all()
        )
    assert len(runs) == 2
    assert runs[1].status == RunStatus.QUEUED.value


async def test_overlap_skip_creates_skipped_record(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
            overlap_policy="skip",
        )
        await _active_run(session, runtime, task, endpoint)
        task_id = task.id

    await SchedulerEngine(runtime).tick(NOW + 100)
    async with session_factory() as session:
        runs = list(
            (await session.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.created_at))).all()
        )
    assert len(runs) == 2
    skipped = runs[1]
    assert skipped.status == RunStatus.SKIPPED.value
    assert skipped.error_type == "overlap"
    assert "has not finished" in (skipped.error_message or "")


async def test_manual_run_obeys_skip_without_changing_schedule(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW + 60_000,
            overlap_policy="skip",
        )
        await _active_run(session, runtime, task, endpoint)
        task_id = task.id
        original_next = task.next_run_at

        run = await run_service.manual_run(
            session, task_id, settings=runtime.settings, now_ms=NOW
        )
        await session.commit()
        task = await session.get(type(task), task_id)
    assert run.status == RunStatus.SKIPPED.value
    assert run.error_type == "overlap"
    assert task.next_run_at == original_next


async def test_manual_run_queues_when_no_overlap(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint)
        run = await run_service.manual_run(
            session, task.id, settings=runtime.settings, now_ms=NOW
        )
        await session.commit()
        task = await session.get(type(task), task.id)
    assert run.status == RunStatus.QUEUED.value
    assert run.trigger_source == "manual"
    assert task.next_run_at is None
