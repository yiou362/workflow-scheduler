"""Shared runtime container wiring the scheduler, dispatcher, executor and SSE."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from promptops.config import Settings
from promptops.dispatcher.pool import RunDispatcher
from promptops.executor.finalizer import finalize_safely
from promptops.executor.handles import HandleRegistry
from promptops.executor.run_executor import RunExecutor
from promptops.executor.sweeper import RunSweeper
from promptops.models import Endpoint
from promptops.opencode.client import OpenCodeV2Client
from promptops.opencode.stream import EventStreamSupervisor
from promptops.scheduler.engine import SchedulerEngine
from promptops.security import SecretBox
from promptops.services.recovery_service import RecoveryService
from promptops.timeutil import Clock, SystemClock
from promptops.trace.ingestor import TraceIngestor

logger = logging.getLogger(__name__)


class Runtime:
    """Holds the long-lived collaborators for one application process."""

    def __init__(
        self,
        *,
        settings: Settings,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        clock: Clock | None = None,
        transport: Any = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.session_factory = session_factory
        self.secret_box = secret_box
        self.clock: Clock = clock or SystemClock()
        self.transport = transport

        self.registry = HandleRegistry()
        self.ingestor = TraceIngestor(self)
        self.stream_supervisor = EventStreamSupervisor(self)
        self.executor = RunExecutor(self)
        self.scheduler = SchedulerEngine(self)
        self.dispatcher = RunDispatcher(self)
        self.sweeper = RunSweeper(self)
        self.recovery = RecoveryService(self)
        self._finalize_tasks: set[asyncio.Task] = set()
        self._started = False

    # ------------------------------------------------------------------ clients
    def make_client(self, endpoint: Endpoint) -> OpenCodeV2Client:
        username: str | None = None
        password = ""
        if endpoint.auth_type == "basic":
            username = endpoint.auth_username or "opencode"
            password = self.secret_box.decrypt(endpoint.secret_ciphertext) or ""
        return OpenCodeV2Client(
            endpoint.base_url,
            username=username,
            password=password,
            connect_timeout=self.settings.http_connect_timeout_seconds,
            read_timeout=self.settings.http_read_timeout_seconds,
            prompt_read_timeout=self.settings.prompt_read_timeout_seconds,
            transport=self.transport,
        )

    # ------------------------------------------------------------------ events
    def ensure_stream(self, endpoint_id: str) -> None:
        self.stream_supervisor.ensure_started(endpoint_id)

    def on_terminal_event(self, run_id: str, kind: str, data: dict[str, Any] | None = None) -> None:
        handle = self.registry.get(run_id)
        if handle is not None:
            handle.set_terminal(kind, data)
            return
        self.schedule_finalize(run_id, kind, data or {})

    def schedule_finalize(self, run_id: str, kind: str, data: dict[str, Any] | None = None) -> None:
        task = asyncio.create_task(
            finalize_safely(self, run_id, kind, data or {}),
            name=f"promptops-finalize-{run_id}",
        )
        self._finalize_tasks.add(task)
        task.add_done_callback(self._finalize_tasks.discard)

    # ------------------------------------------------------------------ lifecycle
    async def start(self, *, run_background: bool = True) -> None:
        if self._started:
            return
        if run_background:
            await self.recovery.recover_on_startup()
            self.scheduler.start()
            self.dispatcher.start()
            self.sweeper.start()
        self._started = True
        logger.info(
            "runtime started workers=%s background=%s",
            self.settings.max_concurrent_runs,
            run_background,
        )

    async def stop(self) -> None:
        self._started = False
        await self.scheduler.stop()
        await self.dispatcher.stop()
        await self.stream_supervisor.stop_all()
        await self.sweeper.stop()
        await self.recovery.stop()
        if self._finalize_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self._finalize_tasks), return_exceptions=True),
                    timeout=self.settings.shutdown_grace_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("shutdown: finalize tasks did not finish in time")
                for task in list(self._finalize_tasks):
                    task.cancel()
        logger.info("runtime stopped")
