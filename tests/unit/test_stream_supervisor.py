from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from promptops.enums import RunStatus, TriggerSource
from promptops.opencode.errors import ConnectionFailed
from promptops.repositories import runs as run_repo
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


class FailingStreamClient:
    def __init__(self) -> None:
        self.closed = 0

    @asynccontextmanager
    async def event_stream(self, *, last_event_id=None):
        async def iterator():
            if False:  # pragma: no cover
                yield None
            raise ConnectionFailed("stream refused")

        yield iterator()

    async def aclose(self) -> None:
        self.closed += 1


async def test_stream_disconnect_marks_trace_gap(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint)
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
        await run_repo.update_fields(
            session, run.id, now=NOW, opencode_session_id="ses_fake", running_at=NOW
        )
        await session.commit()
        run_id = run.id

    fake = FailingStreamClient()
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    runtime.stream_supervisor.ensure_started(endpoint.id)
    await asyncio.sleep(0.2)

    async with session_factory() as session:
        refreshed = await run_repo.get(session, run_id)
    assert refreshed.trace_gap_count >= 1
    assert refreshed.trace_integrity == "gap"
