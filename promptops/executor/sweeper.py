"""Central sweeper: timeouts, cancel-confirmation windows, stale heartbeats."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from promptops.enums import RunStatus
from promptops.opencode.errors import OpenCodeError
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)


class RunSweeper:
    def __init__(self, runtime: "Runtime", interval_seconds: float = 5.0) -> None:
        self.runtime = runtime
        self.interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False
        self._warned: set[str] = set()

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="promptops-sweeper")

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
                await asyncio.sleep(self.interval)
                await self.sweep(self.runtime.clock.now_ms())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - sweeper must survive
                logger.exception("sweeper iteration failed")

    async def sweep(self, now: int) -> None:
        async with self.runtime.session_factory() as session:
            active = await run_repo.active_runs(session)
        for run in active:
            handle = self.runtime.registry.get(run.id)
            try:
                if run.status == RunStatus.CANCELLING.value:
                    await self._handle_cancelling(run, handle, now)
                elif (
                    run.deadline_at is not None
                    and now >= run.deadline_at
                    and run.cancel_reason != "timeout"
                ):
                    await self._request_timeout(run, handle, now)
                if (
                    run.last_heartbeat_at is not None
                    and now - run.last_heartbeat_at > self.runtime.settings.stale_run_seconds * 1000
                    and run.id not in self._warned
                ):
                    self._warned.add(run.id)
                    await self._log(run.id, now, "warn", "stale_heartbeat", "Run heartbeat is stale")
            except Exception:  # noqa: BLE001
                logger.exception("sweeper failed for run %s", run.id)
        self.runtime.stream_supervisor.stop_idle(now)

    async def _request_timeout(self, run, handle, now: int) -> None:  # noqa: ANN001
        if handle is not None:
            handle.request_timeout()
            return
        async with self.runtime.session_factory() as session:
            await run_repo.transition(
                session,
                run.id,
                RunStatus.CANCELLING,
                expected={RunStatus.PREPARING, RunStatus.SUBMITTING, RunStatus.RUNNING, RunStatus.WAITING},
                now=now,
                cancel_requested_at=now,
                cancel_reason="timeout",
            )
            await log_repo.append(
                session, run.id, at=now, phase="timing_out", message="Deadline reached (no handle)"
            )
            await session.commit()

    async def _handle_cancelling(self, run, handle, now: int) -> None:  # noqa: ANN001
        if handle is not None:
            return  # the executor owns confirmation while it is alive
        requested = run.cancel_requested_at or now
        if now - requested < self.runtime.settings.cancel_confirm_seconds * 1000:
            return
        outcome = None
        if run.opencode_session_id and run.endpoint_id:
            async with self.runtime.session_factory() as session:
                endpoint = await endpoint_repo.get(session, run.endpoint_id)
            if endpoint is not None:
                client = self.runtime.make_client(endpoint)
                try:
                    info = await client.session(run.opencode_session_id)
                    outcome = info.outcome
                except OpenCodeError:
                    outcome = None
                finally:
                    await client.aclose()
        if outcome:
            from promptops.executor.finalizer import finalize_safely

            await finalize_safely(self.runtime, run.id, outcome, {})
        else:
            async with self.runtime.session_factory() as session:
                await run_repo.transition(
                    session,
                    run.id,
                    RunStatus.UNKNOWN,
                    expected={RunStatus.CANCELLING},
                    now=now,
                    finished_at=now,
                    error_phase="cancel",
                    error_type="cancel_unconfirmed",
                    error_message="Cancel was requested but execution could not be confirmed as stopped",
                )
                await log_repo.append(
                    session,
                    run.id,
                    at=now,
                    phase="unknown",
                    message="Cancel unconfirmed; marked Unknown",
                    level="error",
                )
                await session.commit()

    async def _log(self, run_id: str, now: int, level: str, phase: str, message: str) -> None:
        async with self.runtime.session_factory() as session:
            await log_repo.append(
                session, run_id, at=now, phase=phase, message=message, level=level
            )
            await session.commit()
