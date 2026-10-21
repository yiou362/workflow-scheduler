from __future__ import annotations

import pytest

from promptops.enums import RunStatus, TriggerSource
from promptops.repositories import runs as run_repo
from promptops.repositories import trace as trace_repo
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def _running_run(session, settings, runtime):
    endpoint = await make_endpoint(session)
    task = await make_task(session, endpoint)
    run = await run_service.create_run(
        session,
        task=task,
        endpoint=endpoint,
        trigger_source=TriggerSource.MANUAL,
        scheduled_for=None,
        occurrence_key=None,
        status=RunStatus.RUNNING,
        settings=settings,
        now_ms=NOW,
    )
    await run_repo.update_fields(
        session, run.id, now=NOW, opencode_session_id="ses_test", running_at=NOW
    )
    await session.commit()
    await session.refresh(run)
    return run


async def _event(runtime, event_type: str, **data):
    await runtime.ingestor.handle_event(
        {"id": f"evt_{event_type}", "type": event_type, "data": {"sessionID": "ses_test", **data}}
    )


@pytest.mark.asyncio
async def test_tool_lifecycle_is_idempotent(runtime, session_factory):
    async with session_factory() as session:
        run = await _running_run(session, runtime.settings, runtime)

    await _event(
        runtime,
        "session.tool.input.started",
        assistantMessageID="msg_a",
        id="call_1",
        name="read",
    )
    await _event(runtime, "session.tool.input.ended", id="call_1", text='{"path": "a.txt"}')
    await _event(
        runtime,
        "session.tool.called",
        id="call_1",
        name="read",
        input={"path": "a.txt"},
        assistantMessageID="msg_a",
    )
    await _event(
        runtime,
        "session.tool.success",
        id="call_1",
        name="read",
        content=[{"type": "text", "text": "file body"}],
        assistantMessageID="msg_a",
    )
    # duplicate delivery must not create a second row
    await _event(
        runtime,
        "session.tool.success",
        id="call_1",
        name="read",
        content=[{"type": "text", "text": "file body"}],
        assistantMessageID="msg_a",
    )

    async with session_factory() as session:
        items = await trace_repo.list_for_run(session, run.id)
    tools = [item for item in items if item.kind == "tool"]
    assert len(tools) == 1
    assert tools[0].name == "read"
    assert tools[0].status == "completed"
    assert tools[0].parent_external_id == "msg_a"
    assert tools[0].output_text == "file body"
    assert tools[0].started_at is not None
    assert tools[0].ended_at is not None


@pytest.mark.asyncio
async def test_text_and_skill_and_permission(runtime, session_factory):
    async with session_factory() as session:
        run = await _running_run(session, runtime.settings, runtime)

    await _event(runtime, "session.text.started", assistantMessageID="msg_a", ordinal=0)
    await _event(runtime, "session.text.delta", assistantMessageID="msg_a", delta="Hello ")
    await _event(runtime, "session.text.delta", assistantMessageID="msg_a", delta="world")
    await _event(runtime, "session.text.ended", assistantMessageID="msg_a", text="Hello world")

    await _event(
        runtime,
        "session.skill.activated",
        id="sk_1",
        name="rates-report",
        description="generates report",
    )
    await _event(
        runtime,
        "permission.asked",
        id="per_1",
        action="bash",
        resources=["rm -rf build"],
        source="tool",
    )

    async with session_factory() as session:
        items = await trace_repo.list_for_run(session, run.id)
        refreshed = await run_repo.get(session, run.id)
    assistant = [item for item in items if item.kind == "assistant_message"]
    assert assistant[0].output_text == "Hello world"
    skill = [item for item in items if item.kind == "skill"]
    assert skill[0].name == "rates-report"
    permission = [item for item in items if item.kind == "permission"]
    assert permission[0].name == "bash"
    assert permission[0].status == "pending"
    assert refreshed.status == RunStatus.WAITING.value


@pytest.mark.asyncio
async def test_project_messages_ignores_reasoning(runtime, session_factory):
    async with session_factory() as session:
        run = await _running_run(session, runtime.settings, runtime)
        messages = [
            {"id": "msg_user", "type": "user", "time": {"created": NOW}, "payload": {"text": "do it"}},
            {
                "id": "msg_a",
                "type": "assistant",
                "time": {"created": NOW + 1, "completed": NOW + 2},
                "content": [
                    {"type": "reasoning", "text": "internal thoughts"},
                    {"type": "text", "text": "visible answer"},
                    {
                        "type": "tool",
                        "id": "call_9",
                        "name": "bash",
                        "time": {"created": NOW + 1, "completed": NOW + 2},
                        "state": {
                            "status": "completed",
                            "input": {"command": "ls"},
                            "content": [{"type": "text", "text": "a.txt"}],
                        },
                    },
                ],
            },
        ]
        await runtime.ingestor.project_messages(session, run, messages, NOW)
        await session.commit()
        items = await trace_repo.list_for_run(session, run.id)

    assert any(item.kind == "user_message" and item.output_text == "do it" for item in items)
    assistant = [item for item in items if item.kind == "assistant_message"][0]
    assert "visible answer" in (assistant.output_text or "")
    assert "internal thoughts" not in (assistant.output_text or "")
    tool = [item for item in items if item.kind == "tool"][0]
    assert tool.parent_external_id == "msg_a"
    assert tool.output_text == "a.txt"


@pytest.mark.asyncio
async def test_trace_text_is_bounded(runtime, session_factory):
    runtime.settings.max_trace_text_bytes = 1024
    async with session_factory() as session:
        run = await _running_run(session, runtime.settings, runtime)
    await _event(runtime, "session.text.ended", assistantMessageID="msg_big", text="x" * 5000)
    async with session_factory() as session:
        items = await trace_repo.list_for_run(session, run.id)
    item = [candidate for candidate in items if candidate.kind == "assistant_message"][0]
    assert len((item.output_text or "").encode("utf-8")) <= 1024
    assert '"truncated": true' in (item.metadata_json or "")
