from sqlalchemy import text


async def test_sqlite_pragmas(engine):
    async with engine.connect() as connection:
        journal = (await connection.execute(text("PRAGMA journal_mode"))).scalar_one()
        foreign_keys = (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one()
        busy_timeout = (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one()
    assert str(journal).lower() == "wal"
    assert int(foreign_keys) == 1
    assert int(busy_timeout) == 5000


async def test_foreign_key_enforced(engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO runs (id, task_id, trigger_source, status, created_at, "
                    "task_name_snapshot, endpoint_name_snapshot, endpoint_url_snapshot, "
                    "endpoint_auth_type_snapshot, working_directory, provider_id, model_id, "
                    "prompt, utc_offset, schedule_summary, overlap_policy, missed_policy, "
                    "timeout_minutes, trace_gap_count, final_response_truncated, "
                    "config_snapshot_json, updated_at) VALUES "
                    "('run_x','tsk_missing','manual','queued',0,'t','e','u','none','/w','p','m',"
                    "'x','+08:00','s','queue','skip',60,0,0,'{}',0)"
                )
            )
