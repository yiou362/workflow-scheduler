"""Shared pytest fixtures.

Every test gets a temporary SQLite file and an injectable clock; nothing touches
the real ``data/`` directory and no test sleeps on wall-clock time.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from promptops.config import Settings
from promptops.db import build_engine, build_session_factory, create_all
from promptops.main import create_app
from promptops.runtime import Runtime
from promptops.security import SecretBox
from promptops.timeutil import FixedClock, parse_iso

START_MS = parse_iso("2026-10-19T00:00:00Z")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        auto_migrate=True,
        utc_offset="+08:00",
        log_level="WARNING",
        default_endpoint_url=None,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START_MS)


@pytest_asyncio.fixture
async def engine(settings):
    settings.ensure_directories()
    engine = build_engine(settings)
    await create_all(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine):
    return build_session_factory(engine)


@pytest_asyncio.fixture
async def session(session_factory):
    async with session_factory() as db_session:
        yield db_session


@pytest_asyncio.fixture
async def runtime(settings, engine, session_factory, clock):
    box = SecretBox(Fernet.generate_key())
    runtime = Runtime(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        secret_box=box,
        clock=clock,
    )
    try:
        yield runtime
    finally:
        await runtime.stop()


@pytest_asyncio.fixture
async def app_context(settings, clock):
    app = create_app(settings, clock=clock, start_background=False)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(app_context):
    transport = httpx.ASGITransport(app=app_context)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        yield api
