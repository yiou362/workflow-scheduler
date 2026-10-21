from __future__ import annotations

from promptops.enums import RunStatus, TriggerSource
from promptops.repositories import runs as run_repo
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def _queued(session, runtime, task, endpoint, now: int | None = None):
    run = await run_service.create_run(
        session,
        task=task,
        endpoint=endpoint,
        trigger_source=TriggerSource.MANUAL,
        scheduled_for=None,
        occurrence_key=None,
        status=RunStatus.QUEUED,
        settings=runtime.settings,
        now_ms=now if now is not None else runtime.clock.now_ms(),
    )
    await session.commit()
    return run


async def test_claim_is_fifo(session, runtime):
    endpoint = await make_endpoint(session)
    task = await make_task(session, endpoint)
    first = await _queued(session, runtime, task, endpoint)
    runtime.clock.advance(10)
    second = await _queued(session, runtime, task, endpoint)

    claimed = await run_repo.claim_next_queued(session, NOW + 20)
    await session.commit()
    assert claimed is not None and claimed.id == first.id

    # A second claim must not start the same Task twice.
    assert await run_repo.claim_next_queued(session, NOW + 20) is None

    # Once the first run reaches a terminal state, the queued run is claimable.
    await run_repo.transition(
        session, first.id, RunStatus.COMPLETED, expected=RunStatus.PREPARING, now=NOW + 30
    )
    await session.commit()
    claimed_second = await run_repo.claim_next_queued(session, NOW + 40)
    await session.commit()
    assert claimed_second is not None and claimed_second.id == second.id


async def test_different_tasks_can_run_in_parallel(session, runtime):
    endpoint = await make_endpoint(session)
    task_a = await make_task(session, endpoint, name="A")
    task_b = await make_task(session, endpoint, name="B")
    run_a = await _queued(session, runtime, task_a, endpoint)
    run_b = await _queued(session, runtime, task_b, endpoint)

    claimed_a = await run_repo.claim_next_queued(session, NOW)
    await session.commit()
    claimed_b = await run_repo.claim_next_queued(session, NOW)
    await session.commit()
    assert claimed_a is not None and claimed_b is not None
    assert {claimed_a.id, claimed_b.id} == {run_a.id, run_b.id}


async def test_claim_sets_deadline_and_heartbeat(session, runtime):
    endpoint = await make_endpoint(session)
    task = await make_task(session, endpoint, timeout_minutes=5)
    await _queued(session, runtime, task, endpoint)
    claimed = await run_repo.claim_next_queued(session, NOW)
    await session.commit()
    assert claimed is not None
    assert claimed.started_at == NOW
    assert claimed.deadline_at == NOW + 5 * 60_000
    assert claimed.last_heartbeat_at == NOW
