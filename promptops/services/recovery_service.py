"""Startup recovery: reconcile active Runs without ever re-sending a Prompt."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from promptops.enums import RunStatus
from promptops.opencode.errors import AuthFailed, ConnectionFailed, OpenCodeError, SessionNotFound
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)

FINAL_STATUSES = {"completed", "failed", "cancelled", "timeout", "skipped", "unknown"}


class RecoveryService:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self._tasks: set[asyncio.Task] = set()

    async def recover_on_startup(self) -> None:
        async with self.runtime.session_factory() as session:
            active = await run_repo.active_runs(session)
        for run in active:
            try:
                await self._recover(run.id)
            except Exception:  # noqa: BLE001 - one Run must not block the rest
                logger.exception("recovery failed for run %s", run.id)
                await self._mark_unknown(run.id, "unexpected", "startup recovery failed")

    async def _recover(self, run_id: str) -> None:
        async with self.runtime.session_factory() as session:
            run = await run_repo.get(session, run_id)
        if run is None or run.status in FINAL_STATUSES:
            return
        now = self.runtime.clock.now_ms()

        if not run.opencode_session_id:
            if run.status == RunStatus.PREPARING.value:
                await self._finish(
                    run_id,
                    RunStatus.FAILED,
                    "session",
                    "process_restarted_before_prompt",
                    "the prompt had not been submitted when the service restarted; no external side effects",
                    now,
                )
            elif run.status == RunStatus.SUBMITTING.value:
                await self._mark_unknown(
                    run_id, "recovery_prompt_may_be_admitted", "the prompt may have been submitted before the service restarted"
                )
            elif run.status == RunStatus.CANCELLING.value:
                await self._finish(
                    run_id, RunStatus.CANCELLED, None, None, "cancel was requested before the restart (no session)", now
                )
            else:
                await self._mark_unknown(run_id, "session_not_found", "no OpenCode session")
            return

        async with self.runtime.session_factory() as session:
            endpoint = await endpoint_repo.get(session, run.endpoint_id) if run.endpoint_id else None
        if endpoint is None or not endpoint.enabled:
            await self._mark_unknown(run_id, "server_unreachable_during_recovery", "endpoint unavailable")
            return
        client = self.runtime.make_client(endpoint)
        try:
            try:
                info = await client.session(run.opencode_session_id)
            except SessionNotFound:
                await self._mark_unknown(run_id, "session_not_found", "session not found in OpenCode")
                return
            except (ConnectionFailed, AuthFailed) as exc:
                await self._mark_unknown(
                    run_id, "server_unreachable_during_recovery", str(exc)
                )
                return
            except OpenCodeError as exc:
                await self._mark_unknown(run_id, "unexpected", str(exc))
                return
            if info.outcome:
                from promptops.executor.finalizer import finalize_safely

                await finalize_safely(self.runtime, run_id, info.outcome, {})
                return
            handle = self.runtime.registry.register(run_id, deadline_at=run.deadline_at)
            handle.attach_session(run.opencode_session_id)
            await self._log(run_id, now, "recovered_active", "Run resumed after process restart")
            if run.deadline_at is not None and run.deadline_at <= now:
                handle.request_timeout()
            if run.cancel_requested_at:
                if run.cancel_reason == "timeout":
                    handle.request_timeout()
                else:
                    handle.request_cancel()
            task = asyncio.create_task(
                self._resume(run_id, handle, client), name=f"promptops-recover-{run_id}"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:
            await client.aclose()
            raise

    async def _resume(self, run_id: str, handle, client) -> None:  # noqa: ANN001
        try:
            await self.runtime.executor.wait_and_finalize(
                run_id, handle, client, prompt_submitted=True
            )
        finally:
            await client.aclose()

    async def _finish(
        self,
        run_id: str,
        status: RunStatus,
        phase: str | None,
        error_type: str | None,
        message: str,
        now: int,
    ) -> None:
        async with self.runtime.session_factory() as session:
            await run_repo.transition(
                session,
                run_id,
                status,
                expected={
                    RunStatus.PREPARING,
                    RunStatus.SUBMITTING,
                    RunStatus.RUNNING,
                    RunStatus.WAITING,
                    RunStatus.CANCELLING,
                },
                now=now,
                finished_at=now,
                error_phase=phase,
                error_type=error_type,
                error_message=message,
            )
            await log_repo.append(
                session,
                run_id,
                at=now,
                phase="recovered",
                message=f"Recovery: {status.value} ({message})",
                level="warn",
            )
            await session.commit()

    async def _mark_unknown(self, run_id: str, error_type: str, message: str) -> None:
        await self._finish(
            run_id, RunStatus.UNKNOWN, "finalize", error_type, message, self.runtime.clock.now_ms()
        )

    async def _log(self, run_id: str, now: int, phase: str, message: str) -> None:
        async with self.runtime.session_factory() as session:
            await log_repo.append(session, run_id, at=now, phase=phase, message=message)
            await session.commit()

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
