"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:  # pragma: no cover - only before startup
        raise RuntimeError("runtime is not initialised")
    return runtime


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    runtime = get_runtime(request)
    session = runtime.session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
