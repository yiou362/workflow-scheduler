"""Dashboard endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.api.dependencies import get_runtime, get_session
from promptops.runtime import Runtime
from promptops.services.dashboard_service import build_dashboard

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard")
async def dashboard(
    session: AsyncSession = Depends(get_session),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await build_dashboard(session, now_ms=runtime.clock.now_ms())
