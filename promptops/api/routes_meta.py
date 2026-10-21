"""Meta and operations endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promptops import __version__
from promptops.api.dependencies import get_runtime, get_session
from promptops.runtime import Runtime
from promptops.timeutil import iso, offset_label

router = APIRouter()


@router.get("/healthz")
async def healthz(
    request: Request,
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    db_status = "ok"
    try:
        await session.execute(text("select 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": __version__,
        "db": db_status,
        "frontend_built": (runtime.settings.frontend_dist / "index.html").exists(),
    }


@router.get("/api/v1/meta")
async def meta(runtime: Runtime = Depends(get_runtime)) -> dict[str, object]:
    now = runtime.clock.now_ms()
    return {
        "version": __version__,
        "server_time": iso(now),
        "utc_offset": runtime.settings.utc_offset,
        "utc_offset_label": offset_label(runtime.settings.utc_offset),
        "frontend_version": None,
    }
