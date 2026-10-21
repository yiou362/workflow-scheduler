from __future__ import annotations

from sqlalchemy import select

from promptops.enums import RunStatus
from promptops.models import Run
from promptops.scheduler.engine import SchedulerEngine
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def test_missed_skip_records_once_and_advances(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=parse_iso("2026-10-18T22:00:00Z"),
            missed_policy="skip",
        )
        task_id = task.id

    await SchedulerEngine(runtime).tick(NOW)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == RunStatus.SKIPPED.value
    assert run.error_type == "missed_schedule"
    assert run.trigger_source == "recovery"
    assert run.error_message is not None and "3" in run.error_message
    assert task.next_run_at is not None and task.next_run_at > NOW


async def test_missed_run_once_creates_single_recovery_run(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=parse_iso("2026-10-18T22:00:00Z"),
            missed_policy="run_once",
        )
        task_id = task.id

    await SchedulerEngine(runtime).tick(NOW)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == RunStatus.QUEUED.value
    assert run.trigger_source == "recovery"
    assert run.scheduled_for == parse_iso("2026-10-19T00:00:00Z")
    assert task.next_run_at is not None and task.next_run_at > NOW


async def test_missed_endpoint_disabled_is_recorded(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session, enabled=False, is_default=False)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="cron",
            cron_expression="0 * * * *",
            next_run_at=parse_iso("2026-10-18T22:00:00Z"),
            missed_policy="run_once",
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SKIPPED.value
    assert runs[0].error_type == "endpoint_disabled"


async def test_one_off_consumed_after_trigger(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="once",
            run_at=NOW,
            next_run_at=NOW,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW + 1)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.QUEUED.value
    assert task.schedule_enabled is False
    assert task.next_run_at is None


async def test_one_off_missed_is_consumed(runtime, session_factory):
    past = parse_iso("2026-10-18T00:00:00Z")
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="once",
            run_at=past,
            next_run_at=past,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    assert runs[0].status == RunStatus.SKIPPED.value
    assert task.schedule_enabled is False
    assert task.next_run_at is None


async def test_interval_advances_without_backlog(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(
            session,
            endpoint,
            schedule_enabled=True,
            schedule_type="interval",
            interval_seconds=1800,
            next_run_at=NOW,
        )
        task_id = task.id
    await SchedulerEngine(runtime).tick(NOW + 1000)
    async with session_factory() as session:
        runs = list((await session.scalars(select(Run).where(Run.task_id == task_id))).all())
        task = await session.get(type(task), task_id)
    assert len(runs) == 1
    assert task.next_run_at == NOW + 1800_000
