"""Per-Endpoint SSE supervision: one stream, lazy start, reconnect with backoff."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from sqlalchemy import update

from promptops.models import Run
from promptops.repositories import endpoints as endpoint_repo
from promptops.repositories import runs as run_repo

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)

IDLE_SECONDS = 300


class EventStreamSupervisor:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self._tasks: dict[str, asyncio.Task] = {}
        self._clients: dict[str, object] = {}
        self._last_activity: dict[str, int] = {}
        self._running = True

    def ensure_started(self, endpoint_id: str) -> None:
        if not self._running:
            return
        task = self._tasks.get(endpoint_id)
        if task is not None and not task.done():
            return
        self._tasks[endpoint_id] = asyncio.create_task(
            self._run(endpoint_id), name=f"promptops-sse-{endpoint_id}"
        )

    async def _run(self, endpoint_id: str) -> None:
        last_event_id: str | None = None
        attempt = 0
        while self._running:
            endpoint = None
            async with self.runtime.session_factory() as session:
                endpoint = await endpoint_repo.get(session, endpoint_id)
            if endpoint is None or not endpoint.enabled:
                break
            client = self.runtime.make_client(endpoint)
            self._clients[endpoint_id] = client
            try:
                async with client.event_stream(last_event_id=last_event_id) as events:
                    attempt = 0
                    self._last_activity[endpoint_id] = self.runtime.clock.now_ms()
                    async for message in events:
                        if not self._running:
                            return
                        payload = message.json()
                        if not payload:
                            continue
                        event_id = payload.get("id")
                        if event_id:
                            last_event_id = str(event_id)
                        await self.runtime.ingestor.handle_event(payload)
                        self._last_activity[endpoint_id] = self.runtime.clock.now_ms()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect on any stream error
                logger.warning("SSE stream error endpoint=%s: %s", endpoint_id, type(exc).__name__)
                await self._record_gap(endpoint_id)
            finally:
                self._clients.pop(endpoint_id, None)
                await client.aclose()
            if not self._running:
                break
            attempt += 1
            delay = min(
                self.runtime.settings.sse_reconnect_max_ms / 1000,
                (self.runtime.settings.sse_reconnect_base_ms / 1000) * (2 ** min(attempt, 6)),
            )
            delay *= 1 + random.uniform(-0.2, 0.2)
            await asyncio.sleep(max(0.2, delay))

    async def _record_gap(self, endpoint_id: str) -> None:
        now = self.runtime.clock.now_ms()
        async with self.runtime.session_factory() as session:
            active = await run_repo.active_runs_for_endpoint(session, endpoint_id)
            for run in active:
                await session.execute(
                    update(Run)
                    .where(Run.id == run.id)
                    .values(
                        trace_gap_count=Run.trace_gap_count + 1,
                        trace_integrity="gap",
                        updated_at=now,
                    )
                )
                logger.warning("trace gap recorded run_id=%s endpoint=%s", run.id, endpoint_id)
            await session.commit()

    def stop_idle(self, now: int) -> None:
        for endpoint_id, task in list(self._tasks.items()):
            if task.done():
                self._tasks.pop(endpoint_id, None)
                continue
            age = now - self._last_activity.get(endpoint_id, now)
            if age < IDLE_SECONDS * 1000:
                continue
            task.cancel()
            self._tasks.pop(endpoint_id, None)
            self._last_activity.pop(endpoint_id, None)

    async def stop_all(self) -> None:
        self._running = False
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks.clear()
