"""Execute a claimed Run: prepare, submit, wait, cancel/timeout, finalize."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from promptops.enums import RunStatus
from promptops.opencode.client import OpenCodeV2Client, model_ref
from promptops.opencode.errors import (
    AuthFailed,
    ConnectionFailed,
    HttpError,
    OpenCodeError,
    OpenCodeTimeout,
    PromptRejected,
    PromptUncertain,
    ProtocolError,
    SessionNotFound,
    UnsupportedServer,
)
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.executor.finalizer import finalize_safely

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)


class RunExecutor:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime

    async def execute_run(self, run_id: str) -> None:
        runtime = self.runtime
        now = runtime.clock.now_ms()
        async with runtime.session_factory() as session:
            run = await run_repo.get(session, run_id)
        if run is None or run.status != RunStatus.PREPARING.value:
            return
        handle = runtime.registry.register(run_id, deadline_at=run.deadline_at)
        client: OpenCodeV2Client | None = None
        prompt_submitted = False
        try:
            if handle.cancel_requested:
                await self._finish_direct(run_id, RunStatus.CANCELLED, "user", now)
                return
            if handle.timeout_requested:
                await self._finish_direct(run_id, RunStatus.TIMEOUT, "timeout_before_prompt", now)
                return

            endpoint = None
            if run.endpoint_id:
                async with runtime.session_factory() as session:
                    endpoint = await endpoint_repo.get(session, run.endpoint_id)
            if endpoint is None or not endpoint.enabled:
                await self._mark_skipped(run_id, "endpoint_disabled", now)
                return
            await self._log(run_id, "resolving_endpoint", f"Resolving endpoint {endpoint.id}")
            client = runtime.make_client(endpoint)

            await self._log(run_id, "probing", "Probing OpenCode v2 endpoint")
            await client.probe()
            if await self._control_check(run_id, handle, prompt_submitted=False):
                return

            await self._log(run_id, "creating_session", "Creating OpenCode session")
            session_info = await client.create_session(
                title=self._title(run),
                directory=run.working_directory,
                model=model_ref(run.provider_id, run.model_id, run.model_variant),
                agent=run.agent,
            )
            now = runtime.clock.now_ms()
            async with runtime.session_factory() as session:
                await run_repo.update_fields(
                    session,
                    run_id,
                    now=now,
                    opencode_session_id=session_info.id,
                    opencode_session_title=session_info.title,
                )
                await session.commit()
            handle.attach_session(session_info.id)
            runtime.ensure_stream(endpoint.id)
            await self._log(
                run_id, "session_created", f"Session {session_info.id} created"
            )
            if await self._control_check(run_id, handle, prompt_submitted=False):
                return

            now = runtime.clock.now_ms()
            await self._transition(run_id, RunStatus.SUBMITTING, now, submitting_at=now)
            await self._log(run_id, "submitting", "Submitting prompt")
            submit_started = runtime.clock.now_ms()
            try:
                user_message = await client.prompt(session_info.id, run.prompt)
                prompt_submitted = True
                await self._transition(
                    run_id, RunStatus.RUNNING, runtime.clock.now_ms(), running_at=runtime.clock.now_ms()
                )
                await self._log(
                    run_id,
                    "submitted",
                    f"Prompt admitted (user message {user_message.id or 'unknown'})",
                )
            except PromptUncertain as exc:
                admitted = await self._reconcile_admission(
                    client, session_info.id, run.prompt, submit_started
                )
                if not admitted:
                    await self._finish_unknown(run_id, "prompt_admission_unknown", str(exc))
                    return
                prompt_submitted = True
                await self._transition(
                    run_id, RunStatus.RUNNING, runtime.clock.now_ms(), running_at=runtime.clock.now_ms()
                )
                await self._log(run_id, "submitted", "Prompt admission confirmed by reconciliation")
            await self._log(run_id, "tracing", "Tracing session")
            await self.wait_and_finalize(run_id, handle, client, prompt_submitted=True)
        except PromptRejected as exc:
            await self._finish_failed(run_id, "prompt", "prompt_rejected", str(exc))
        except AuthFailed as exc:
            await self._finish_failed(run_id, "connect", "connect_auth_failed", str(exc))
        except ConnectionFailed as exc:
            await self._finish_failed(run_id, "connect", "connect_unreachable", str(exc))
        except UnsupportedServer as exc:
            await self._finish_failed(run_id, "connect", "connect_unsupported", str(exc))
        except OpenCodeTimeout as exc:
            await self._finish_failed(run_id, "connect", "connect_timeout", str(exc))
        except HttpError as exc:
            await self._finish_failed(run_id, "connect", "connect_service_error", str(exc))
        except ProtocolError as exc:
            await self._finish_failed(run_id, "connect", "connect_unsupported", str(exc))
        except Exception as exc:  # noqa: BLE001 - never kill the worker
            logger.exception("unexpected executor error run_id=%s", run_id)
            await self._finish_failed(run_id, "session", "unexpected", type(exc).__name__)
        finally:
            if client is not None:
                await client.aclose()
            runtime.registry.unregister(run_id)

    # ------------------------------------------------------------------ wait
    async def wait_and_finalize(
        self,
        run_id: str,
        handle,  # noqa: ANN001 - RunHandle
        client: OpenCodeV2Client,
        *,
        prompt_submitted: bool,
    ) -> None:
        runtime = self.runtime
        session_id = handle.session_id
        stop_initiated = False
        last_poll = 0
        while True:
            now = runtime.clock.now_ms()
            if handle.terminal:
                await finalize_safely(runtime, run_id, handle.terminal_kind or "succeeded", handle.terminal_data)
                return
            if handle.cancel_requested or handle.timeout_requested:
                if not prompt_submitted or session_id is None:
                    reason = "timeout" if handle.timeout_requested else "user"
                    status = RunStatus.TIMEOUT if reason == "timeout" else RunStatus.CANCELLED
                    await self._finish_direct(run_id, status, reason, now)
                    return
                if not stop_initiated:
                    stop_initiated = True
                    reason = "timeout" if handle.timeout_requested else "user"
                    await self._request_stop(run_id, handle, reason, now)
                    try:
                        interrupted = await client.interrupt(session_id)
                        await self._log(
                            run_id,
                            "interrupt_sent",
                            f"Interrupt acknowledged (interrupted={interrupted})",
                        )
                    except SessionNotFound:
                        await self._finish_unknown(run_id, "session_not_found", "Session not found")
                        return
                    except OpenCodeError as exc:
                        await self._log(
                            run_id,
                            "cancelling",
                            f"Interrupt request failed: {exc}",
                            level="warn",
                        )
                confirmed = await handle.wait_terminal(
                    timeout=runtime.settings.cancel_confirm_seconds
                )
                if confirmed:
                    await finalize_safely(runtime, run_id, confirmed, handle.terminal_data)
                    return
                await self._finish_after_unconfirmed(run_id, client, session_id)
                return
            if handle.deadline_at is not None and now >= handle.deadline_at:
                handle.request_timeout()
                await self._log(run_id, "timing_out", "Deadline reached; requesting interrupt")
                continue
            # Polling fallback when SSE has gone quiet.
            last_event = handle.last_event_at or 0
            if (
                session_id
                and now - last_event > runtime.settings.sse_stale_seconds * 1000
                and now - last_poll > 5_000
            ):
                last_poll = now
                try:
                    info = await client.session(session_id)
                    if info.outcome:
                        await finalize_safely(runtime, run_id, info.outcome, {})
                        return
                except OpenCodeError:
                    pass
            remaining = 5.0
            if handle.deadline_at is not None:
                remaining = min(remaining, max(0.1, (handle.deadline_at - now) / 1000))
            await handle.wait_change(timeout=remaining)

    async def _finish_after_unconfirmed(
        self, run_id: str, client: OpenCodeV2Client, session_id: str | None
    ) -> None:
        if session_id:
            try:
                info = await client.session(session_id)
                if info.outcome:
                    await finalize_safely(self.runtime, run_id, info.outcome, {})
                    return
            except OpenCodeError:
                pass
        await self._finish_unknown(run_id, "cancel_unconfirmed", "cancel/timeout could not be confirmed as stopped")

    # ------------------------------------------------------------------ admission
    async def _reconcile_admission(
        self,
        client: OpenCodeV2Client,
        session_id: str,
        prompt: str,
        submit_started: int,
    ) -> bool:
        await asyncio.sleep(1.0)
        try:
            page = await client.messages(
                session_id, order="desc", limit=5, message_type="user"
            )
        except OpenCodeError:
            return False
        for message in page.messages:
            payload = message.get("payload") or {}
            text = payload.get("text") if isinstance(payload, dict) else None
            created = (message.get("time") or {}).get("created")
            if text == prompt and (created is None or created >= submit_started):
                return True
        return False

    # ------------------------------------------------------------------ control
    async def _control_check(
        self, run_id: str, handle, *, prompt_submitted: bool  # noqa: ANN001
    ) -> bool:
        now = self.runtime.clock.now_ms()
        if handle.deadline_at is not None and now >= handle.deadline_at:
            handle.request_timeout()
        if handle.timeout_requested:
            status = RunStatus.TIMEOUT if not prompt_submitted else RunStatus.CANCELLING
            await self._finish_direct(run_id, status, "timeout_before_prompt", now)
            return True
        if handle.cancel_requested:
            if not prompt_submitted:
                await self._finish_direct(run_id, RunStatus.CANCELLED, "user", now)
            else:
                await self._request_stop(run_id, handle, "user", now)
            return True
        return False

    async def _request_stop(self, run_id: str, handle, reason: str, now: int) -> None:  # noqa: ANN001
        await self._transition(
            run_id,
            RunStatus.CANCELLING,
            now,
            cancel_requested_at=now,
            cancel_reason=reason,
        )
        await self._log(run_id, "cancelling", f"Cancel requested (reason={reason})")

    # ------------------------------------------------------------------ terminal helpers
    async def _finish_direct(
        self, run_id: str, status: RunStatus, reason: str, now: int
    ) -> None:
        is_timeout = status == RunStatus.TIMEOUT
        error_type = "timeout_before_prompt" if is_timeout else None
        async with self.runtime.session_factory() as session:
            applied = await run_repo.transition(
                session,
                run_id,
                status,
                expected={RunStatus.PREPARING, RunStatus.SUBMITTING, RunStatus.CANCELLING},
                now=now,
                finished_at=now,
                cancel_requested_at=now,
                cancel_confirmed_at=now,
                cancel_reason="timeout" if is_timeout else "user",
                error_phase="timeout" if is_timeout else None,
                error_type=error_type,
            )
            await log_repo.append(
                session,
                run_id,
                at=now,
                phase="cancel_confirmed",
                message=f"Run stopped before prompt: {status.value}",
            )
            await session.commit()
        self.runtime.registry.unregister(run_id)

    async def _finish_failed(
        self, run_id: str, phase: str, error_type: str, message: str
    ) -> None:
        now = self.runtime.clock.now_ms()
        async with self.runtime.session_factory() as session:
            applied = await run_repo.transition(
                session,
                run_id,
                RunStatus.FAILED,
                expected={RunStatus.PREPARING, RunStatus.SUBMITTING, RunStatus.RUNNING, RunStatus.WAITING, RunStatus.CANCELLING},
                now=now,
                finished_at=now,
                error_phase=phase,
                error_type=error_type,
                error_message=message,
            )
            if applied:
                await log_repo.append(
                    session,
                    run_id,
                    at=now,
                    phase="failed",
                    message=f"Failed at {phase}: {error_type}",
                    level="error",
                )
            await session.commit()
        self.runtime.registry.unregister(run_id)

    async def _finish_unknown(self, run_id: str, error_type: str, message: str) -> None:
        now = self.runtime.clock.now_ms()
        async with self.runtime.session_factory() as session:
            await run_repo.transition(
                session,
                run_id,
                RunStatus.UNKNOWN,
                expected={RunStatus.PREPARING, RunStatus.SUBMITTING, RunStatus.RUNNING, RunStatus.WAITING, RunStatus.CANCELLING},
                now=now,
                finished_at=now,
                error_phase="finalize",
                error_type=error_type,
                error_message=message,
                trace_integrity="incomplete",
            )
            await log_repo.append(
                session,
                run_id,
                at=now,
                phase="unknown",
                message=f"Cannot confirm run state: {error_type}",
                level="error",
            )
            await session.commit()
        self.runtime.registry.unregister(run_id)

    async def _mark_skipped(self, run_id: str, error_type: str, now: int) -> None:
        async with self.runtime.session_factory() as session:
            await run_repo.transition(
                session,
                run_id,
                RunStatus.SKIPPED,
                expected={RunStatus.PREPARING},
                now=now,
                finished_at=now,
                error_phase="scheduler",
                error_type=error_type,
                error_message="Endpoint is disabled; prompt not sent",
            )
            await log_repo.append(
                session,
                run_id,
                at=now,
                phase="skipped",
                message=f"Skipped: {error_type}",
                level="warn",
            )
            await session.commit()
        self.runtime.registry.unregister(run_id)

    async def _transition(self, run_id: str, status: RunStatus, now: int, **fields: Any) -> bool:
        async with self.runtime.session_factory() as session:
            applied = await run_repo.transition(
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
                **fields,
            )
            await session.commit()
        return applied

    async def _log(
        self,
        run_id: str,
        phase: str,
        message: str,
        *,
        level: str = "info",
    ) -> None:
        async with self.runtime.session_factory() as session:
            await log_repo.append(
                session, run_id, at=self.runtime.clock.now_ms(), phase=phase, message=message, level=level
            )
            await session.commit()

    @staticmethod
    def _title(run) -> str:  # noqa: ANN001 - ORM Run
        title = f"PromptOps · {run.task_name_snapshot} · {run.id}"
        return title[:80]
