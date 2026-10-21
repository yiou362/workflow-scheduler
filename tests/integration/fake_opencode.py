"""A scriptable in-process double for the OpenCode v2 client.

The executor/finalizer only use the adapter interface, so a fake class is enough
to exercise the whole Run lifecycle without a real server.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from promptops.opencode.client import (
    AgentOption,
    FileDiff,
    MessagePage,
    ModelOption,
    ServerInfo,
    SessionInfo,
    UserMessage,
)


class FakeOpenCodeClient:
    def __init__(
        self,
        runtime,
        *,
        outcome: str = "succeeded",
        messages: list[dict[str, Any]] | None = None,
        diffs: list[FileDiff] | None = None,
        prompt_error: Exception | None = None,
        probe_error: Exception | None = None,
        auto_terminal: bool = True,
        interrupt_terminal: bool = True,
        session_outcome_after: str | None = None,
        tokens: dict[str, Any] | None = None,
        cost: float | None = 0.01,
        advance_on_prompt_ms: int = 0,
    ) -> None:
        self.runtime = runtime
        self.outcome = outcome
        self.messages_list = messages if messages is not None else default_messages()
        self.diffs = diffs if diffs is not None else [FileDiff(file="out.txt", patch="+hello", additions=1, deletions=0, status="added")]
        self.prompt_error = prompt_error
        self.probe_error = probe_error
        self.auto_terminal = auto_terminal
        self.interrupt_terminal = interrupt_terminal
        self.session_outcome_after = session_outcome_after
        self.tokens = tokens if tokens is not None else {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}}
        self.cost = cost
        self.advance_on_prompt_ms = advance_on_prompt_ms
        self.prompt_calls = 0
        self.prompts: list[str] = []
        self.sessions_created = 0
        self.interrupt_calls = 0
        self.closed = 0
        self._outcome: str | None = None
        self._last_session: str | None = None

    async def probe(self) -> ServerInfo:
        if self.probe_error:
            raise self.probe_error
        return ServerInfo(version="2.0.29", pid=1, urls=["http://fake"], paths={})

    async def create_session(self, *, title: str, directory: str, model: dict | None, agent: str | None) -> SessionInfo:
        self.sessions_created += 1
        self._last_session = "ses_fake"
        return SessionInfo(id="ses_fake", title=title, raw={"id": "ses_fake", "title": title})

    async def prompt(self, session_id: str, text: str) -> UserMessage:
        self.prompt_calls += 1
        self.prompts.append(text)
        if self.advance_on_prompt_ms:
            self.runtime.clock.advance(self.advance_on_prompt_ms)
        if self.prompt_error:
            if self.auto_terminal:
                self._outcome = self.outcome
                handle = self.runtime.registry.by_session(session_id)
                if handle is not None:
                    asyncio.get_running_loop().call_later(0.05, handle.set_terminal, self.outcome)
            raise self.prompt_error
        if self.auto_terminal:
            self._outcome = self.outcome
            handle = self.runtime.registry.by_session(session_id)
            if handle is not None:
                asyncio.get_running_loop().call_later(0.05, handle.set_terminal, self.outcome)
        return UserMessage(id="msg_user", raw={"id": "msg_user"})

    async def session(self, session_id: str) -> SessionInfo:
        outcome = self._outcome
        if self.session_outcome_after is not None:
            outcome = self.session_outcome_after
        return SessionInfo(
            id=session_id,
            outcome=outcome,
            cost=self.cost,
            tokens=self.tokens,
            raw={},
        )

    async def messages(
        self,
        session_id: str,
        *,
        order: str = "asc",
        limit: int = 100,
        cursor: str | None = None,
        message_type: str | None = None,
    ) -> MessagePage:
        items = self.messages_list
        if message_type == "user":
            items = [item for item in items if item.get("type") == "user"]
            if order == "desc":
                items = list(reversed(items))
        return MessagePage(messages=items[:limit], next_cursor=None)

    async def diff(self, session_id: str) -> list[FileDiff]:
        return self.diffs

    async def interrupt(self, session_id: str) -> bool:
        self.interrupt_calls += 1
        if self.interrupt_terminal:
            handle = self.runtime.registry.by_session(session_id)
            if handle is not None:
                asyncio.get_running_loop().call_later(0.05, handle.set_terminal, "interrupted")
        return True

    async def reply_permission(self, session_id: str, request_id: str, decision: str, message: str | None = None) -> None:
        return None

    async def models(self, directory: str) -> list[ModelOption]:
        return [ModelOption(provider_id="lps", model_id="m1", name="Model 1", variants=["thinking"])]

    async def agents(self, directory: str) -> list[AgentOption]:
        return [AgentOption(id="build", name="Build")]

    @asynccontextmanager
    async def event_stream(self, *, last_event_id: str | None = None):
        async def empty():
            if False:  # pragma: no cover - produces an empty async iterator
                yield None

        yield empty()

    async def aclose(self) -> None:
        self.closed += 1


def default_messages() -> list[dict[str, Any]]:
    return [
        {
            "id": "msg_user",
            "type": "user",
            "time": {"created": 1792400404038},
            "payload": {"text": "处理本月的工时数据并生成 Rate Report。"},
        },
        {
            "id": "msg_assistant",
            "type": "assistant",
            "time": {"created": 2, "completed": 3},
            "content": [
                {"type": "text", "text": "已完成 Rate Report。"},
                {
                    "type": "tool",
                    "id": "call_1",
                    "name": "read",
                    "executed": True,
                    "time": {"created": 2, "completed": 3},
                    "state": {
                        "status": "completed",
                        "input": {"path": "hours.xlsx"},
                        "content": [{"type": "text", "text": "hours"}],
                    },
                },
            ],
            "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 1, "write": 0}},
            "cost": 0.01,
        },
    ]
