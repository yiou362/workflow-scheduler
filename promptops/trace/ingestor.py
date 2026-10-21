"""Normalise OpenCode v2 SSE events into trace items and Run transitions.

Rules honoured here:
* trace items only come from observed events/messages, never inferred;
* reasoning content is ignored;
* file changes are authoritative only from ``/diff``;
* unknown events are ignored and logged at debug level;
* text deltas are throttled to avoid one DB write per character.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.domain.trace import collapse_content_parts, json_text, map_tool_status, truncate_text
from promptops.enums import RunStatus, TraceKind, TraceStatus
from promptops.models import Run
from promptops.repositories import logs as log_repo
from promptops.repositories import runs as run_repo
from promptops.repositories import trace as trace_repo

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)

_TEXT_FLUSH_INTERVAL_MS = 500
_TEXT_FLUSH_BYTES = 4096


class TraceIngestor:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self._text: dict[tuple[str, str], list[Any]] = {}
        self.unknown_events = 0

    @property
    def _sessions(self):  # noqa: ANN201
        return self.runtime.session_factory

    async def handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        session_id = data.get("sessionID")
        if not session_id:
            return
        async with self._sessions() as session:
            run = await run_repo.get_by_session(session, str(session_id))
            if run is None:
                return
            handle = self.runtime.registry.by_session(str(session_id))
            if handle is not None:
                handle.last_event_at = self.runtime.clock.now_ms()
            await self._dispatch(session, run, event_type, data, event)
            await session.commit()

    async def _dispatch(
        self,
        session: AsyncSession,
        run: Run,
        event_type: str,
        data: dict[str, Any],
        event: dict[str, Any],
    ) -> None:
        now = self.runtime.clock.now_ms()
        if event_type.startswith("session.text."):
            await self._on_text(session, run, event_type, data, now)
        elif event_type.startswith("session.tool."):
            await self._on_tool(session, run, event_type, data, now)
        elif event_type == "session.skill.activated":
            await self._on_skill(session, run, data, now)
        elif event_type == "permission.asked":
            await self._on_permission_asked(session, run, data, event, now)
        elif event_type == "permission.replied":
            await self._on_permission_replied(session, run, data, now)
        elif event_type in ("session.execution.started", "session.inbox.delivered"):
            await run_repo.transition(
                session,
                run.id,
                RunStatus.RUNNING,
                expected={RunStatus.SUBMITTING},
                now=now,
                running_at=now,
            )
        elif event_type == "session.created":
            title = data.get("title")
            if title and run.opencode_session_title != title:
                await run_repo.update_fields(
                    session, run.id, now=now, opencode_session_title=str(title)
                )
        elif event_type == "session.step.ended":
            await self._on_step_ended(session, run, data, now)
        elif event_type == "session.usage.updated":
            await self._on_usage(session, run, data, now)
        elif event_type.startswith("session.execution.") and event_type.endswith(
            ("succeeded", "failed", "interrupted")
        ):
            kind = event_type.rsplit(".", 1)[-1]
            self.runtime.on_terminal_event(run.id, kind, data)
        elif event_type == "session.error":
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.ERROR.value,
                external_id=str(event.get("id") or f"error:{now}"),
                now=now,
                name="session.error",
                status=TraceStatus.FAILED.value,
                error_text=json.dumps(data, ensure_ascii=False)[:2000],
                metadata={"event_type": event_type},
            )
        elif event_type in ("file.edited",):
            logger.debug("file.edited observed; /diff remains authoritative")
        else:
            self.unknown_events += 1
            logger.debug("ignoring unknown event type=%s", event_type)

    # ------------------------------------------------------------------ text
    async def _on_text(
        self, session: AsyncSession, run: Run, event_type: str, data: dict[str, Any], now: int
    ) -> None:
        message_id = data.get("assistantMessageID") or data.get("messageID") or data.get("id")
        if not message_id:
            return
        key = (run.id, str(message_id))
        if event_type == "session.text.started":
            self._text[key] = ["", now]
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.ASSISTANT_MESSAGE.value,
                external_id=str(message_id),
                now=now,
                status=TraceStatus.PENDING.value,
                started_at=now,
                output_text="",
            )
            return
        if event_type == "session.text.delta":
            buffer = self._text.setdefault(key, ["", now])
            buffer[0] = str(buffer[0]) + str(data.get("delta") or "")
            encoded_len = len(str(buffer[0]).encode("utf-8"))
            if encoded_len >= _TEXT_FLUSH_BYTES or now - int(buffer[1]) >= _TEXT_FLUSH_INTERVAL_MS:
                await self._flush_text(session, run, str(message_id), buffer, now)
            return
        if event_type == "session.text.ended":
            text = data.get("text")
            final = str(text) if text is not None else str(self._text.get(key, ["", now])[0])
            self._text.pop(key, None)
            bounded, truncated, original = truncate_text(final, self.runtime.settings.max_trace_text_bytes)
            metadata = {"truncated": truncated, "original_bytes": original} if truncated else None
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.ASSISTANT_MESSAGE.value,
                external_id=str(message_id),
                now=now,
                status=TraceStatus.COMPLETED.value,
                ended_at=now,
                output_text=bounded,
                metadata=metadata,
            )

    async def _flush_text(
        self, session: AsyncSession, run: Run, message_id: str, buffer: list[Any], now: int
    ) -> None:
        text = str(buffer[0])
        bounded, truncated, original = truncate_text(text, self.runtime.settings.max_trace_text_bytes)
        metadata = {"truncated": truncated, "original_bytes": original} if truncated else None
        await trace_repo.upsert(
            session,
            run.id,
            kind=TraceKind.ASSISTANT_MESSAGE.value,
            external_id=message_id,
            now=now,
            status=TraceStatus.RUNNING.value,
            output_text=bounded,
            metadata=metadata,
        )
        buffer[1] = now

    # ------------------------------------------------------------------ tools
    async def _on_tool(
        self, session: AsyncSession, run: Run, event_type: str, data: dict[str, Any], now: int
    ) -> None:
        call_id = data.get("id") or data.get("callID")
        if not call_id:
            return
        parent = data.get("assistantMessageID")
        name = data.get("name")
        if event_type == "session.tool.input.started":
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=str(parent) if parent else None,
                name=str(name) if name else None,
                status=TraceStatus.PENDING.value,
                started_at=now,
            )
        elif event_type == "session.tool.input.ended":
            text = data.get("text")
            input_json: str | None
            try:
                parsed = json.loads(text) if text else None
                input_json = json.dumps(parsed, ensure_ascii=False) if parsed is not None else None
            except (TypeError, ValueError):
                input_json = json.dumps(str(text), ensure_ascii=False) if text is not None else None
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=str(parent) if parent else None,
                name=str(name) if name else None,
                status=TraceStatus.RUNNING.value,
                input_json=input_json,
            )
        elif event_type == "session.tool.called":
            input_json = json.dumps(data.get("input"), ensure_ascii=False) if data.get("input") is not None else None
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=str(parent) if parent else None,
                name=str(name) if name else None,
                status=TraceStatus.RUNNING.value,
                started_at=now,
                input_json=input_json,
            )
        elif event_type == "session.tool.success":
            content = collapse_content_parts(data.get("content"))
            bounded, truncated, original = truncate_text(
                content, self.runtime.settings.max_trace_text_bytes
            )
            metadata = {"truncated": truncated, "original_bytes": original} if truncated else None
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=str(parent) if parent else None,
                name=str(name) if name else None,
                status=TraceStatus.COMPLETED.value,
                ended_at=now,
                output_text=bounded,
                metadata=metadata,
            )
        elif event_type == "session.tool.failed":
            error = data.get("error")
            error_text = (
                error
                if isinstance(error, str)
                else json.dumps(error, ensure_ascii=False)
                if error is not None
                else None
            )
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=str(parent) if parent else None,
                name=str(name) if name else None,
                status=TraceStatus.FAILED.value,
                ended_at=now,
                error_text=error_text,
            )
        elif event_type == "session.tool.progress":
            content = collapse_content_parts(data.get("content"))
            if content:
                bounded, _, _ = truncate_text(content, self.runtime.settings.max_trace_text_bytes)
                await trace_repo.upsert(
                    session,
                    run.id,
                    kind=TraceKind.TOOL.value,
                    external_id=str(call_id),
                    now=now,
                    status=TraceStatus.RUNNING.value,
                    output_text=bounded,
                )

    # ------------------------------------------------------------------ skill
    async def _on_skill(
        self, session: AsyncSession, run: Run, data: dict[str, Any], now: int
    ) -> None:
        skill = data.get("skill") if isinstance(data.get("skill"), dict) else {}
        name = (
            data.get("name")
            or skill.get("name")
            or data.get("skill")
            or data.get("skillID")
            or data.get("id")
        )
        external_id = data.get("id") or data.get("skillID") or f"skill:{name}"
        await trace_repo.upsert(
            session,
            run.id,
            kind=TraceKind.SKILL.value,
            external_id=str(external_id),
            now=now,
            name=str(name) if name else "skill",
            status=TraceStatus.INFO.value,
            started_at=now,
            output_text=data.get("description") or data.get("result"),
            metadata={"source": "session.skill.activated"},
        )

    # ------------------------------------------------------------------ permission
    async def _on_permission_asked(
        self,
        session: AsyncSession,
        run: Run,
        data: dict[str, Any],
        event: dict[str, Any],
        now: int,
    ) -> None:
        request = data.get("request") if isinstance(data.get("request"), dict) else data
        request_id = request.get("id") or data.get("id")
        if not request_id:
            return
        resources = request.get("resources")
        source = request.get("source")
        metadata: dict[str, Any] = {
            "save": request.get("save"),
            "metadata": request.get("metadata"),
            "message": request.get("message"),
            "source": source,
        }
        await trace_repo.upsert(
            session,
            run.id,
            kind=TraceKind.PERMISSION.value,
            external_id=str(request_id),
            now=now,
            name=str(request.get("action") or data.get("action") or "permission"),
            status=TraceStatus.PENDING.value,
            started_at=now,
            input_json=json.dumps(
                {"resources": resources, "source": source}, ensure_ascii=False
            )
            if resources is not None or source is not None
            else None,
            metadata=metadata,
        )
        await run_repo.transition(
            session,
            run.id,
            RunStatus.RUNNING,
            expected=RunStatus.SUBMITTING,
            now=now,
        )
        await run_repo.transition(
            session,
            run.id,
            RunStatus.WAITING,
            expected=RunStatus.RUNNING,
            now=now,
        )
        await log_repo.append(
            session,
            run.id,
            at=now,
            phase="waiting_permission",
            message=f"Waiting for permission: {request.get('action') or 'permission'}",
        )

    async def _on_permission_replied(
        self, session: AsyncSession, run: Run, data: dict[str, Any], now: int
    ) -> None:
        reply = data.get("reply") if isinstance(data.get("reply"), dict) else data
        request_id = reply.get("requestID") or reply.get("requestId") or reply.get("id")
        if not request_id:
            return
        decision = reply.get("decision")
        if decision is None:
            return
        status = TraceStatus.REJECTED.value if decision == "reject" else TraceStatus.COMPLETED.value
        await trace_repo.upsert(
            session,
            run.id,
            kind=TraceKind.PERMISSION.value,
            external_id=str(request_id),
            now=now,
            status=status,
            metadata={"decision": decision},
        )

    # ------------------------------------------------------------------ usage
    async def _on_step_ended(
        self, session: AsyncSession, run: Run, data: dict[str, Any], now: int
    ) -> None:
        tokens = data.get("tokens")
        cost = data.get("cost")
        await self._apply_usage(session, run, tokens, cost)

    async def _on_usage(
        self, session: AsyncSession, run: Run, data: dict[str, Any], now: int
    ) -> None:
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
        await self._apply_usage(session, run, tokens, data.get("cost"))

    async def _apply_usage(
        self, session: AsyncSession, run: Run, tokens: Any, cost: Any
    ) -> None:
        values: dict[str, Any] = {}
        if isinstance(tokens, dict):
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            if tokens.get("input") is not None:
                values["input_tokens"] = int(tokens["input"])
            if tokens.get("output") is not None:
                values["output_tokens"] = int(tokens["output"])
            if tokens.get("reasoning") is not None:
                values["reasoning_tokens"] = int(tokens["reasoning"])
            if cache.get("read") is not None:
                values["cache_read_tokens"] = int(cache["read"])
            if cache.get("write") is not None:
                values["cache_write_tokens"] = int(cache["write"])
        if cost is not None:
            try:
                values["cost_usd"] = float(cost)
            except (TypeError, ValueError):
                pass
        if values:
            await session.execute(update(Run).where(Run.id == run.id).values(**values))

    # ------------------------------------------------------------------ helpers
    async def project_messages(
        self, session: AsyncSession, run: Run, messages: list[dict[str, Any]], now: int
    ) -> None:
        for message in messages:
            message_type = message.get("type")
            message_id = message.get("id")
            if not message_id:
                continue
            if message_type == "user":
                payload = message.get("payload") or {}
                text = payload.get("text") if isinstance(payload, dict) else None
                await trace_repo.upsert(
                    session,
                    run.id,
                    kind=TraceKind.USER_MESSAGE.value,
                    external_id=str(message_id),
                    now=now,
                    started_at=(message.get("time") or {}).get("created") or now,
                    output_text=text,
                    status=TraceStatus.COMPLETED.value,
                )
            elif message_type == "assistant":
                await self._project_assistant_message(session, run, message, now)
            elif message_type == "skill":
                name = message.get("name") or message.get("skill")
                await trace_repo.upsert(
                    session,
                    run.id,
                    kind=TraceKind.SKILL.value,
                    external_id=str(message_id),
                    now=now,
                    name=str(name) if name else "skill",
                    status=TraceStatus.INFO.value,
                    started_at=(message.get("time") or {}).get("created") or now,
                    output_text=collapse_content_parts(message.get("content")) or message.get("text"),
                )
            elif message_type == "shell":
                await trace_repo.upsert(
                    session,
                    run.id,
                    kind=TraceKind.TOOL.value,
                    external_id=str(message_id),
                    now=now,
                    name="shell",
                    status=TraceStatus.COMPLETED.value,
                    output_text=collapse_content_parts(message.get("content")),
                )

    async def _project_assistant_message(
        self, session: AsyncSession, run: Run, message: dict[str, Any], now: int
    ) -> None:
        message_id = str(message.get("id"))
        content = message.get("content")
        text = collapse_content_parts(content)
        times = message.get("time") or {}
        bounded, truncated, original = truncate_text(
            text or None, self.runtime.settings.max_trace_text_bytes
        )
        metadata = {"truncated": truncated, "original_bytes": original} if truncated else None
        await trace_repo.upsert(
            session,
            run.id,
            kind=TraceKind.ASSISTANT_MESSAGE.value,
            external_id=message_id,
            now=now,
            status=TraceStatus.COMPLETED.value,
            started_at=times.get("created") or now,
            ended_at=times.get("completed") or times.get("created") or now,
            output_text=bounded,
            metadata=metadata,
        )
        if not isinstance(content, list):
            return
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            call_id = part.get("id")
            if not call_id:
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            status = map_tool_status(state.get("status"))
            input_value = state.get("input")
            output = collapse_content_parts(state.get("content"))
            error = state.get("error")
            part_times = part.get("time") or {}
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.TOOL.value,
                external_id=str(call_id),
                now=now,
                parent_external_id=message_id,
                name=str(part.get("name") or "tool"),
                status=status,
                started_at=part_times.get("created"),
                ended_at=part_times.get("completed") or part_times.get("ran"),
                input_json=json_text(input_value),
                output_text=output or None,
                error_text=error if isinstance(error, str) else json_text(error),
                metadata={"executed": part.get("executed")},
            )

    async def project_diffs(
        self, session: AsyncSession, run: Run, diffs: list[Any], now: int
    ) -> None:
        for diff in diffs:
            bounded, truncated, original = truncate_text(
                diff.patch, self.runtime.settings.max_trace_text_bytes
            )
            metadata: dict[str, Any] = {
                "status": diff.status,
                "additions": diff.additions,
                "deletions": diff.deletions,
                "truncated": truncated,
                "original_bytes": original,
            }
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.FILE.value,
                external_id=diff.file,
                now=now,
                name=diff.file,
                status=TraceStatus.INFO.value,
                output_text=bounded,
                metadata=metadata,
            )

    async def register_file_gap(
        self, session: AsyncSession, run: Run, files: list[str], now: int
    ) -> None:
        for path in files:
            await trace_repo.upsert(
                session,
                run.id,
                kind=TraceKind.FILE.value,
                external_id=str(path),
                now=now,
                name=str(path),
                status=TraceStatus.INFO.value,
                error_text="Could not retrieve the diff",
                metadata={"status": "unknown"},
            )


def compute_usage_from_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Last assistant message tokens/cost (no estimation)."""

    usage: dict[str, Any] = {}
    for message in messages:
        if message.get("type") != "assistant":
            continue
        tokens = message.get("tokens")
        if isinstance(tokens, dict):
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            usage.update(
                {
                    "input_tokens": tokens.get("input"),
                    "output_tokens": tokens.get("output"),
                    "reasoning_tokens": tokens.get("reasoning"),
                    "cache_read_tokens": cache.get("read"),
                    "cache_write_tokens": cache.get("write"),
                }
            )
        if message.get("cost") is not None:
            usage["cost_usd"] = message.get("cost")
    return {key: value for key, value in usage.items() if value is not None}


def compute_final_response(messages: list[dict[str, Any]], max_bytes: int) -> tuple[str | None, bool]:
    """Final response = last assistant message, only if it has non-empty text."""

    for message in reversed(messages):
        if message.get("type") != "assistant":
            continue
        text = collapse_content_parts(message.get("content"))
        if not text.strip():
            return None, False
        bounded, truncated, _ = truncate_text(text, max_bytes)
        return bounded, truncated
    return None, False
