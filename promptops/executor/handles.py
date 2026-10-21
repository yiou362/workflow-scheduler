"""In-memory execution handles.

A handle is registered as soon as a Run is claimed (before any session exists) so
the UI can cancel it.  Terminal events are latched: ``set_terminal`` followed by
``wait`` returns immediately, so an event that arrives before the executor starts
waiting is never lost.
"""

from __future__ import annotations

import asyncio
from typing import Any


class RunHandle:
    def __init__(self, run_id: str, *, deadline_at: int | None = None) -> None:
        self.run_id = run_id
        self.session_id: str | None = None
        self.deadline_at = deadline_at
        self.terminal_event = asyncio.Event()
        self.terminal_kind: str | None = None
        self.terminal_data: dict[str, Any] | None = None
        self.cancel_requested = False
        self.timeout_requested = False
        self.cancel_reason: str | None = None
        self.last_event_at: int | None = None
        self._wake = asyncio.Event()

    def attach_session(self, session_id: str) -> None:
        self.session_id = session_id

    def set_terminal(self, kind: str, data: dict[str, Any] | None = None) -> None:
        if self.terminal_kind is not None:
            return
        self.terminal_kind = kind
        self.terminal_data = data or {}
        self.terminal_event.set()
        self._wake.set()

    def request_cancel(self) -> None:
        self.cancel_requested = True
        self.cancel_reason = "user"
        self._wake.set()

    def request_timeout(self) -> None:
        self.timeout_requested = True
        self.cancel_reason = "timeout"
        self._wake.set()

    @property
    def terminal(self) -> bool:
        return self.terminal_kind is not None

    async def wait_terminal(self, timeout: float | None = None) -> str | None:
        try:
            await asyncio.wait_for(self.terminal_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self.terminal_kind

    async def wait_change(self, timeout: float | None = None) -> None:
        """Wait for a terminal event, cancel/timeout request, or timeout."""

        if self.terminal_event.is_set() or self._wake.is_set():
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            self._wake.clear()


class HandleRegistry:
    def __init__(self) -> None:
        self._by_run: dict[str, RunHandle] = {}

    def register(self, run_id: str, *, deadline_at: int | None = None) -> RunHandle:
        existing = self._by_run.get(run_id)
        if existing is not None:
            return existing
        handle = RunHandle(run_id, deadline_at=deadline_at)
        self._by_run[run_id] = handle
        return handle

    def get(self, run_id: str) -> RunHandle | None:
        return self._by_run.get(run_id)

    def by_session(self, session_id: str) -> RunHandle | None:
        for handle in self._by_run.values():
            if handle.session_id == session_id:
                return handle
        return None

    def unregister(self, run_id: str) -> None:
        self._by_run.pop(run_id, None)

    def all(self) -> list[RunHandle]:
        return list(self._by_run.values())

    def __len__(self) -> int:
        return len(self._by_run)
