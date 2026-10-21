"""Run finalization: reconcile messages/diff, compute final response and close.

``finalize`` is idempotent, may be called by the executor, the SSE supervisor or
recovery, and must never leave a Run in an active state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from promptops.domain.state_machine import status_after_terminal_event
from promptops.enums import (
    ACTIVE_RUN_STATUSES,
    RunStatus,
    TraceIntegrity,
)
from promptops.opencode.errors import OpenCodeError, SessionNotFound
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.trace.ingestor import (
    TraceIngestor,
    compute_final_response,
    compute_usage_from_messages,
)

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)

_ACTIVE_VALUES = [item.value for item in ACTIVE_RUN_STATUSES]
_TERMINAL_VALUES = {"completed", "failed", "cancelled", "timeout", "skipped", "unknown"}


def _status_for(kind: str, cancel_reason: str | None) -> tuple[RunStatus, str | None, str | None]:
    if kind == "succeeded":
        return RunStatus.COMPLETED, None, None
    if kind == "failed":
        return RunStatus.FAILED, "session_failed", "OpenCode session ended as failed"
    if kind == "interrupted":
        if cancel_reason == "user":
            return RunStatus.CANCELLED, None, None
        if cancel_reason == "timeout":
            return RunStatus.TIMEOUT, None, None
        return RunStatus.FAILED, "remote_interrupted", "Session was interrupted externally, not by this system"
    if kind == "unconfirmed":
        error_type = (
            "timeout_unconfirmed" if cancel_reason == "timeout" else "cancel_unconfirmed"
        )
        return RunStatus.UNKNOWN, error_type, "Cannot confirm whether execution stopped"
    return RunStatus.UNKNOWN, "unexpected", f"unknown terminal state: {kind}"


async def finalize(
    runtime: "Runtime", run_id: str, kind: str, data: dict[str, Any] | None = None
) -> None:
    now = runtime.clock.now_ms()
    async with runtime.session_factory() as session:
        run = await run_repo.get(session, run_id)
    if run is None:
        return
    if run.status in _TERMINAL_VALUES:
        return

    status, error_type, error_message = _status_for(kind, run.cancel_reason)
    client = None
    endpoint = None
    if run.endpoint_id:
        async with runtime.session_factory() as session:
            endpoint = await endpoint_repo.get(session, run.endpoint_id)
    if endpoint is not None:
        client = runtime.make_client(endpoint)

    messages: list[dict[str, Any]] = []
    diffs: list[Any] = []
    session_info = None
    message_error = False
    diff_error = False
    session_error = False

    try:
        if client is not None and run.opencode_session_id:
            try:
                session_info = await client.session(run.opencode_session_id)
            except SessionNotFound:
                session_error = True
            except OpenCodeError:
                session_error = True
            # Give the SSE writer a moment to persist the terminal batch.
            await asyncio.sleep(0.5)
            page = None
            cursor = None
            pages = 0
            try:
                while pages < runtime.settings.max_message_pages:
                    page = await client.messages(
                        run.opencode_session_id, order="asc", limit=100, cursor=cursor
                    )
                    messages.extend(page.messages)
                    pages += 1
                    if not page.next_cursor:
                        break
                    cursor = page.next_cursor
            except OpenCodeError:
                message_error = True
            try:
                diffs = await client.diff(run.opencode_session_id)
            except OpenCodeError:
                diff_error = True
    finally:
        if client is not None:
            await client.aclose()

    if session_info is not None and session_info.outcome and kind not in ("succeeded", "failed"):
        kind = session_info.outcome
        status, error_type, error_message = _status_for(kind, run.cancel_reason)
    if kind == "succeeded" and status == RunStatus.COMPLETED:
        error_type, error_message = None, None
    if status == RunStatus.FAILED and messages:
        # OpenCode reports provider/session failures on the idle projection.
        for message in reversed(messages):
            if message.get("type") != "idle":
                continue
            error = message.get("error")
            if isinstance(error, dict) and (error.get("type") or error.get("message")):
                error_message = f"{error.get('type') or 'error'}: {error.get('message') or ''}".strip()
            break

    usage = compute_usage_from_messages(messages)
    if session_info is not None:
        if session_info.tokens:
            tokens = session_info.tokens
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            usage.update(
                {
                    key: value
                    for key, value in {
                        "input_tokens": tokens.get("input"),
                        "output_tokens": tokens.get("output"),
                        "reasoning_tokens": tokens.get("reasoning"),
                        "cache_read_tokens": cache.get("read"),
                        "cache_write_tokens": cache.get("write"),
                    }.items()
                    if value is not None
                }
            )
        if session_info.cost is not None:
            usage["cost_usd"] = session_info.cost

    final_text, truncated = compute_final_response(
        messages, runtime.settings.max_trace_text_bytes
    )
    if not messages and message_error:
        integrity = TraceIntegrity.INCOMPLETE.value
    elif run.trace_gap_count and run.trace_gap_count > 0:
        integrity = TraceIntegrity.GAP.value
    elif message_error or diff_error:
        integrity = TraceIntegrity.INCOMPLETE.value
    elif not messages and not diffs:
        integrity = TraceIntegrity.NONE.value
    else:
        integrity = TraceIntegrity.COMPLETE.value

    ingestor: TraceIngestor = runtime.ingestor
    error_phase = None
    if status == RunStatus.FAILED:
        error_phase = "session"
    elif kind == "unconfirmed":
        error_phase = "timeout" if run.cancel_reason == "timeout" else "cancel"
    elif session_error:
        error_phase = "finalize"
    async with runtime.session_factory() as session:
        terminal_fields: dict[str, Any] = {}
        if status in (RunStatus.CANCELLED, RunStatus.TIMEOUT):
            terminal_fields["cancel_confirmed_at"] = now
        applied = await run_repo.transition(
            session,
            run_id,
            status,
            expected=set(_ACTIVE_VALUES),
            now=now,
            finished_at=now,
            final_response=final_text,
            final_response_truncated=truncated,
            error_phase=error_phase,
            error_type=error_type,
            error_message=error_message,
            trace_integrity=integrity,
            **terminal_fields,
            **usage,
        )
        if messages:
            await ingestor.project_messages(session, run, messages, now)
        if diffs:
            await ingestor.project_diffs(session, run, diffs, now)
        if applied:
            await log_repo.append(
                session,
                run_id,
                at=now,
                phase="finalized",
                message=f"Run finished: {status.value}",
                level="info" if status == RunStatus.COMPLETED else "warn",
                details={"trace_integrity": integrity},
            )
        await session.commit()

    handle = runtime.registry.get(run_id)
    if handle is not None:
        handle.set_terminal(kind)
    runtime.registry.unregister(run_id)
    logger.info("run finalized run_id=%s status=%s", run_id, status.value)


async def finalize_safely(
    runtime: "Runtime", run_id: str, kind: str, data: dict[str, Any] | None = None
) -> None:
    """Finalize without ever leaving the Run active on an unexpected error."""

    try:
        await finalize(runtime, run_id, kind, data)
    except Exception as exc:  # noqa: BLE001 - must not leak
        logger.exception("finalize failed run_id=%s", run_id)
        now = runtime.clock.now_ms()
        try:
            async with runtime.session_factory() as session:
                await run_repo.transition(
                    session,
                    run_id,
                    RunStatus.UNKNOWN,
                    expected=set(_ACTIVE_VALUES),
                    now=now,
                    finished_at=now,
                    error_phase="finalize",
                    error_type="finalize_failed",
                    error_message=f"finalization failed: {type(exc).__name__}",
                    trace_integrity=TraceIntegrity.INCOMPLETE.value,
                )
                await log_repo.append(
                    session,
                    run_id,
                    at=now,
                    phase="failed",
                    message="Finalize failed; run marked Unknown",
                    level="error",
                )
                await session.commit()
        finally:
            runtime.registry.unregister(run_id)


def status_after_event(kind: str, cancel_reason: str | None) -> RunStatus:
    if kind in ("succeeded", "failed", "interrupted"):
        return status_after_terminal_event(f"session.execution.{kind}", cancel_reason=cancel_reason)
    return RunStatus.UNKNOWN
