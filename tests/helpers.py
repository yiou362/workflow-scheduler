"""Test data builders."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from promptops.ids import new_id
from promptops.models import Endpoint, Task
from promptops.security import SecretBox
from promptops.timeutil import now_ms


async def make_endpoint(
    session: AsyncSession,
    *,
    name: str = "Local OpenCode",
    base_url: str = "http://127.0.0.1:4096",
    auth_type: str = "none",
    username: str | None = None,
    password: str | None = None,
    is_default: bool = True,
    enabled: bool = True,
    box: SecretBox | None = None,
) -> Endpoint:
    timestamp = now_ms()
    endpoint = Endpoint(
        id=new_id("endpoint"),
        name=name,
        description=None,
        base_url=base_url,
        auth_type=auth_type,
        auth_username=username,
        secret_ciphertext=box.encrypt(password) if (box and password) else None,
        is_default=is_default,
        enabled=enabled,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(endpoint)
    await session.commit()
    return endpoint


async def make_task(
    session: AsyncSession,
    endpoint: Endpoint,
    *,
    name: str = "Monthly Rate Report",
    prompt: str = "处理本月的工时数据并生成 Rate Report。",
    status: str = "enabled",
    schedule_enabled: bool = False,
    schedule_type: str = "none",
    cron_expression: str | None = None,
    run_at: int | None = None,
    interval_seconds: int | None = None,
    next_run_at: int | None = None,
    overlap_policy: str = "queue",
    missed_policy: str = "skip",
    timeout_minutes: int = 60,
    tags: list[str] | None = None,
    **overrides: Any,
) -> Task:
    timestamp = now_ms()
    import json

    task = Task(
        id=new_id("task"),
        name=name,
        description=None,
        tags_json=json.dumps(tags or []),
        endpoint_id=endpoint.id,
        working_directory="/workspace/rates-report",
        provider_id="lps",
        model_id="Qwen/Qwen3.6-35B-A3B-FP8",
        model_variant="thinking",
        agent=None,
        prompt=prompt,
        status=status,
        schedule_enabled=schedule_enabled,
        schedule_type=schedule_type,
        cron_expression=cron_expression,
        run_at=run_at,
        interval_seconds=interval_seconds,
        overlap_policy=overlap_policy,
        missed_policy=missed_policy,
        timeout_minutes=timeout_minutes,
        next_run_at=next_run_at,
        created_at=timestamp,
        updated_at=timestamp,
        **overrides,
    )
    session.add(task)
    await session.commit()
    return task
