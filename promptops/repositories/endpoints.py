"""Endpoint repository."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from promptops.models import Endpoint, Task


async def get(session: AsyncSession, endpoint_id: str) -> Endpoint | None:
    return await session.get(Endpoint, endpoint_id)


async def get_by_name(session: AsyncSession, name: str) -> Endpoint | None:
    return await session.scalar(select(Endpoint).where(func.lower(Endpoint.name) == name.lower()))


async def get_default(session: AsyncSession) -> Endpoint | None:
    return await session.scalar(select(Endpoint).where(Endpoint.is_default.is_(True)))


async def count(session: AsyncSession, *, enabled: bool | None = None) -> int:
    stmt = select(func.count()).select_from(Endpoint)
    if enabled is not None:
        stmt = stmt.where(Endpoint.enabled.is_(enabled))
    return int(await session.scalar(stmt) or 0)


async def list_page(
    session: AsyncSession, *, enabled: bool | None, offset: int, limit: int
) -> tuple[list[Endpoint], int]:
    stmt = select(Endpoint)
    count_stmt = select(func.count()).select_from(Endpoint)
    if enabled is not None:
        stmt = stmt.where(Endpoint.enabled.is_(enabled))
        count_stmt = count_stmt.where(Endpoint.enabled.is_(enabled))
    stmt = stmt.order_by(Endpoint.created_at.asc()).offset(offset).limit(limit)
    items = list((await session.scalars(stmt)).all())
    total = int(await session.scalar(count_stmt) or 0)
    return items, total


async def task_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(Task.endpoint_id, func.count()).select_from(Task).group_by(Task.endpoint_id)
    )
    return {endpoint_id: int(total) for endpoint_id, total in rows.all()}


async def task_count_for(session: AsyncSession, endpoint_id: str) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(Task).where(Task.endpoint_id == endpoint_id)) or 0
    )


async def create(session: AsyncSession, endpoint: Endpoint) -> Endpoint:
    session.add(endpoint)
    await session.flush()
    return endpoint


async def clear_default(session: AsyncSession) -> None:
    await session.execute(update(Endpoint).where(Endpoint.is_default.is_(True)).values(is_default=False))


async def delete(session: AsyncSession, endpoint: Endpoint) -> None:
    await session.delete(endpoint)
    await session.flush()
