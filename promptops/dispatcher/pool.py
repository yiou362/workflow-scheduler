"""Dispatcher: N workers claim Queued Runs and execute them."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from promptops.repositories import runs as run_repo

if TYPE_CHECKING:  # pragma: no cover
    from promptops.runtime import Runtime

logger = logging.getLogger(__name__)


class RunDispatcher:
    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.workers = runtime.settings.max_concurrent_runs
        self._tasks: list[asyncio.Task] = []
        self._claim_lock = asyncio.Lock()
        self._running = False

    def start(self) -> None:
        self._running = True
        for index in range(self.workers):
            self._tasks.append(
                asyncio.create_task(self._worker(index), name=f"promptops-worker-{index}")
            )

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.exception("dispatcher worker stopped with an error")
        self._tasks.clear()

    async def _worker(self, index: int) -> None:
        while self._running:
            try:
                run_id = await self._claim()
                if run_id is None:
                    await asyncio.sleep(0.5)
                    continue
                await self.runtime.executor.execute_run(run_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one Run must not kill the worker
                logger.exception("dispatcher worker %s failed", index)
                await asyncio.sleep(0.5)

    async def _claim(self) -> str | None:
        async with self._claim_lock:
            async with self.runtime.session_factory() as session:
                run = await run_repo.claim_next_queued(
                    session, self.runtime.clock.now_ms()
                )
                if run is None:
                    return None
                run_id = run.id
                await session.commit()
            return run_id
