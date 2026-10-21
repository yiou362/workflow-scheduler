"""Async SQLAlchemy engine, sessions and SQLite pragmas."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from promptops.config import Settings
from promptops.models import Base

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_engine(settings: Settings) -> AsyncEngine:
    engine = create_async_engine(settings.resolved_database_url, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Commit on success, roll back on error, always close."""

    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_sqlite_version(engine: AsyncEngine) -> str:
    async with engine.connect() as connection:
        result = await connection.execute(text("select sqlite_version()"))
        version = str(result.scalar_one())
    parts = tuple(int(part) for part in version.split(".")[:3])
    if parts < (3, 38, 0):
        raise RuntimeError(f"SQLite >= 3.38 is required (found {version})")
    return version


def alembic_config(settings: Settings) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.resolved_database_url)
    # Keep the application's JSON logging instead of Alembic's config.
    config.attributes["skip_logging_config"] = True
    return config


def run_migrations(settings: Settings) -> None:
    """Run ``alembic upgrade head`` (blocking; call via ``asyncio.to_thread``)."""

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings), "head")


async def run_migrations_async(settings: Settings) -> None:
    await asyncio.to_thread(run_migrations, settings)


async def create_all(engine: AsyncEngine) -> None:
    """Test helper: create the schema directly from ORM metadata."""

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()
