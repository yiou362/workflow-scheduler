from __future__ import annotations

from sqlalchemy import select

from promptops.enums import RunStatus
from promptops.models import Run
from promptops.repositories import runs as run_repo
from promptops.scheduler.engine import SchedulerEngine
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def test_due_task_creates_exactly_one_run(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
        )
        task_id = task.id

    scheduler = SchedulerEngine(runtime)
    await scheduler.tick(NOW + 100)
    await scheduler.tick(NOW + 200)

    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.QUEUED.value
    assert runs[0].occurrence_key == f"occ:{NOW}"
    assert runs[0].trigger_source == "scheduled"
    assert task.next_run_at is not None and task.next_run_at > NOW


async def test_occurrence_is_idempotent_when_duplicate_tick(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
        )
        task_id = task.id

    scheduler = SchedulerEngine(runtime)
    await scheduler.tick(NOW + 100)
    # Force the same occurrence back, as if the clock/advance was rolled back.
    async with session_factory() as session:
        task = await session.get(type(task), task_id)
        task.next_run_at = NOW
        await session.commit()

    await scheduler.tick(NOW + 200)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
    assert len(runs) == 1


async def test_no_due_task_no_run(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW + 3600_000,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
    assert runs == []


async def test_disabled_task_not_scheduled(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            status="disabled",
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW + 1)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
    assert runs == []


async def test_endpoint_disabled_creates_skipped(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session, enabled=False, is_default=False)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=NOW,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW + 1)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SKIPPED.value
    assert runs[0].error_type == "endpoint_disabled"
