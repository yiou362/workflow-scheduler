import json

from promptops.domain.snapshots import build_run_snapshot, dump_snapshot
from promptops.enums import RunStatus, TriggerSource
from promptops.repositories import runs as run_repo
from promptops.services import run_service
from promptops.timeutil import parse_iso
from tests.helpers import make_endpoint, make_task

NOW = parse_iso("2026-10-19T00:00:00Z")


async def test_snapshot_contains_required_fields_and_no_password(session, runtime):
    endpoint = await make_endpoint(
        session,
        auth_type="basic",
        username="opencode",
        password="hunter2",
        box=runtime.secret_box,
    )
    task = await make_task(session, endpoint)
    snapshot = build_run_snapshot(
        task=task,
        endpoint=endpoint,
        trigger_source="scheduled",
        scheduled_for=NOW,
        utc_offset="+08:00",
    )
    assert snapshot["task"]["name"] == task.name
    assert snapshot["endpoint"]["base_url"] == endpoint.base_url
    assert snapshot["execution"]["working_directory"] == task.working_directory
    assert snapshot["prompt"] == task.prompt
    assert snapshot["schedule"]["utc_offset"] == "+08:00"
    assert snapshot["policy"]["timeout_minutes"] == 60
    serialized = dump_snapshot(snapshot)
    assert "hunter2" not in serialized
    assert "secret" not in serialized.lower()


async def test_task_edits_do_not_change_existing_run(session, runtime):
    endpoint = await make_endpoint(session)
    task = await make_task(session, endpoint)
    run = await run_service.create_run(
        session,
        task=task,
        endpoint=endpoint,
        trigger_source=TriggerSource.SCHEDULED,
        scheduled_for=NOW,
        occurrence_key=f"occ:{NOW}",
        status=RunStatus.QUEUED,
        settings=runtime.settings,
        now_ms=NOW,
    )
    original_prompt = run.prompt
    original_snapshot = run.config_snapshot_json

    task.name = "Changed Name"
    task.prompt = "different prompt"
    task.model_id = "other-model"
    await session.commit()

    refreshed = await run_repo.get(session, run.id)
    assert refreshed.task_name_snapshot != "Changed Name"
    assert refreshed.prompt == original_prompt
    assert refreshed.config_snapshot_json == original_snapshot
    snapshot = json.loads(refreshed.config_snapshot_json)
    assert snapshot["prompt"] == original_prompt
