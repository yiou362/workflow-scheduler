from __future__ import annotations

import asyncio

import pytest

from promptops.enums import RunStatus, TriggerSource
from promptops.opencode.errors import ConnectionFailed, PromptUncertain
from promptops.repositories import runs as run_repo
from promptops.repositories import trace as trace_repo
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task
from tests.integration.fake_opencode import FakeOpenCodeClient

NOW = parse_iso("2026-10-19T00:00:00Z")


async def _queued(runtime, session_factory, **task_overrides):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint, **task_overrides)
        run = await run_service.create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=TriggerSource.MANUAL,
            scheduled_for=None,
            occurrence_key=None,
            status=RunStatus.QUEUED,
            settings=runtime.settings,
            now_ms=NOW,
        )
        await session.commit()
        return run.id


async def _claim(runtime, run_id):
    async with runtime.session_factory() as session:
        claimed = await run_repo.claim_next_queued(session, runtime.clock.now_ms())
        await session.commit()
    assert claimed is not None and claimed.id == run_id
    return claimed


async def _reload(runtime, run_id):
    async with runtime.session_factory() as session:
        return await run_repo.get(session, run_id)


@pytest.mark.asyncio
async def test_executor_completes_run_and_records_trace(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(runtime)
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    await runtime.executor.execute_run(run_id)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert run.final_response == "已完成 Rate Report。"
    assert run.opencode_session_id == "ses_fake"
    assert run.input_tokens == 10
    assert run.output_tokens == 5
    assert run.cost_usd == 0.01
    assert run.trace_integrity == "complete"
    assert run.finished_at is not None
    assert fake.prompt_calls == 1
    assert fake.prompts == [make_endpoint_prompt()]

    async with runtime.session_factory() as session:
        items = await trace_repo.list_for_run(session, run_id)
    kinds = {item.kind for item in items}
    assert {"user_message", "assistant_message", "tool", "file"} <= kinds
    tool = [item for item in items if item.kind == "tool"][0]
    assert tool.name == "read"
    assert tool.parent_external_id == "msg_assistant"


def make_endpoint_prompt() -> str:
    return "处理本月的工时数据并生成 Rate Report。"


@pytest.mark.asyncio
async def test_prompt_uncertain_is_not_resent(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(
        runtime,
        prompt_error=PromptUncertain("connection dropped"),
        messages=[],
    )
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    await runtime.executor.execute_run(run_id)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.UNKNOWN.value
    assert run.error_type == "prompt_admission_unknown"
    assert fake.prompt_calls == 1


@pytest.mark.asyncio
async def test_prompt_admission_reconciled_continues(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    from tests.integration.fake_opencode import default_messages

    fake = FakeOpenCodeClient(
        runtime,
        prompt_error=PromptUncertain("read timeout"),
        messages=default_messages(),
    )
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    await runtime.executor.execute_run(run_id)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert fake.prompt_calls == 1


@pytest.mark.asyncio
async def test_connection_failure_marks_failed_without_switching(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(runtime, probe_error=ConnectionFailed("refused"))
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    await runtime.executor.execute_run(run_id)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.FAILED.value
    assert run.error_phase == "connect"
    assert run.error_type == "connect_unreachable"
    assert fake.sessions_created == 0


@pytest.mark.asyncio
async def test_cancel_running_run_waits_for_confirmation(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(runtime, auto_terminal=False, interrupt_terminal=True)
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    task = asyncio.create_task(runtime.executor.execute_run(run_id))
    await asyncio.sleep(0.2)
    async with runtime.session_factory() as session:
        await run_service.request_cancel(
            session, run_id, registry=runtime.registry, now_ms=runtime.clock.now_ms()
        )
        await session.commit()
    await asyncio.wait_for(task, timeout=5)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.CANCELLED.value
    assert run.cancel_reason == "user"
    assert run.cancel_confirmed_at is not None
    assert fake.interrupt_calls == 1


@pytest.mark.asyncio
async def test_cancel_unconfirmed_becomes_unknown(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    runtime.settings.cancel_confirm_seconds = 1
    fake = FakeOpenCodeClient(runtime, auto_terminal=False, interrupt_terminal=False)
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    task = asyncio.create_task(runtime.executor.execute_run(run_id))
    await asyncio.sleep(0.2)
    async with runtime.session_factory() as session:
        await run_service.request_cancel(
            session, run_id, registry=runtime.registry, now_ms=runtime.clock.now_ms()
        )
        await session.commit()
    await asyncio.wait_for(task, timeout=8)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.UNKNOWN.value
    assert run.error_type == "cancel_unconfirmed"


@pytest.mark.asyncio
async def test_timeout_before_prompt_is_direct(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(runtime, auto_terminal=False)
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    claimed = await _claim(runtime, run_id)
    # Deadline already elapsed: no prompt has been submitted, so no interrupt is needed.
    async with runtime.session_factory() as session:
        await run_repo.update_fields(session, run_id, now=NOW, deadline_at=NOW - 1)
        await session.commit()

    await runtime.executor.execute_run(run_id)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.TIMEOUT.value
    assert run.error_type == "timeout_before_prompt"
    assert fake.prompt_calls == 0
    assert fake.interrupt_calls == 0


@pytest.mark.asyncio
async def test_timeout_after_prompt_becomes_timeout(runtime, session_factory):
    run_id = await _queued(runtime, session_factory)
    fake = FakeOpenCodeClient(
        runtime,
        auto_terminal=False,
        interrupt_terminal=True,
        advance_on_prompt_ms=61 * 60 * 1000,
    )
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await _claim(runtime, run_id)

    await asyncio.wait_for(runtime.executor.execute_run(run_id), timeout=5)

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.TIMEOUT.value
    assert fake.prompt_calls == 1
    assert fake.interrupt_calls == 1


@pytest.mark.asyncio
async def test_recovery_finalizes_session_without_resending_prompt(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint)
        run = await run_service.create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=TriggerSource.SCHEDULED,
            scheduled_for=NOW,
            occurrence_key=f"occ:{NOW}",
            status=RunStatus.RUNNING,
            settings=runtime.settings,
            now_ms=NOW,
        )
        await run_repo.update_fields(
            session, run.id, now=NOW, opencode_session_id="ses_fake", running_at=NOW
        )
        await session.commit()
        run_id = run.id

    fake = FakeOpenCodeClient(runtime, session_outcome_after="succeeded")
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    await runtime.recovery.recover_on_startup()

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.COMPLETED.value
    assert fake.prompt_calls == 0


@pytest.mark.asyncio
async def test_recovery_without_session_does_not_replay(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint)
        run = await run_service.create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=TriggerSource.MANUAL,
            scheduled_for=None,
            occurrence_key=None,
            status=RunStatus.PREPARING,
            settings=runtime.settings,
            now_ms=NOW,
        )
        await session.commit()
        run_id = run.id

    await runtime.recovery.recover_on_startup()

    run = await _reload(runtime, run_id)
    assert run.status == RunStatus.FAILED.value
    assert run.error_type == "process_restarted_before_prompt"


@pytest.mark.asyncio
async def test_permission_reply_moves_run_back_to_running(runtime, session_factory):
    async with session_factory() as session:
        endpoint = await make_endpoint(session)
        task = await make_task(session, endpoint)
        run = await run_service.create_run(
            session,
            task=task,
            endpoint=endpoint,
            trigger_source=TriggerSource.MANUAL,
            scheduled_for=None,
            occurrence_key=None,
            status=RunStatus.WAITING,
            settings=runtime.settings,
            now_ms=NOW,
        )
        await run_repo.update_fields(
            session, run.id, now=NOW, opencode_session_id="ses_fake", running_at=NOW
        )
        await trace_repo.upsert(
            session,
            run.id,
            kind="permission",
            external_id="per_1",
            now=NOW,
            name="bash",
            status="pending",
        )
        await session.commit()
        run_id = run.id

    fake = FakeOpenCodeClient(runtime)
    runtime.make_client = lambda endpoint: fake  # type: ignore[method-assign]
    async with runtime.session_factory() as session:
        await run_service.reply_permission(
            session,
            run_id,
            "per_1",
            decision="once",
            message=None,
            runtime=runtime,
            now_ms=runtime.clock.now_ms(),
        )
        await session.commit()
        refreshed = await run_repo.get(session, run_id)
        item = await trace_repo.get(session, run_id, "permission", "per_1")
    assert refreshed.status == RunStatus.RUNNING.value
    assert item is not None and item.status == "completed"
