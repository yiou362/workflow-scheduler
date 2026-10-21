"""Append-only Run lifecycle log repository."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.ids import new_id
from promptops.logging import redact_text
from promptops.models import RunLog


async def append(
    session: AsyncSession,
    run_id: str,
    *,
    at: int,
    phase: str,
    message: str,
    level: str = "info",
    details: dict[str, object] | None = None,
) -> RunLog:
    entry = RunLog(
        id=new_id("log"),
        run_id=run_id,
        at=at,
        level=level,
        phase=phase,
        message=redact_text(message) or "",
        details_json=json.dumps(details, ensure_ascii=False, sort_keys=True) if details else None,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_for_run(
    session: AsyncSession, run_id: str, *, after_at: int | None = None, limit: int = 500
) -> list[RunLog]:
    stmt = select(RunLog).where(RunLog.run_id == run_id)
    if after_at is not None:
        stmt = stmt.where(RunLog.at > after_at)
    stmt = stmt.order_by(RunLog.at.asc(), RunLog.id.asc()).limit(min(max(limit, 1), 2000))
    return list((await session.scalars(stmt)).all())
