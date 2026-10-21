"""Initial PromptOps schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

RUN_STATUSES = (
    "queued",
    "preparing",
    "submitting",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
    "timeout",
    "skipped",
    "unknown",
)


def upgrade() -> None:
    op.create_table(
        "endpoints",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.Text(), nullable=False, server_default="none"),
        sa.Column("auth_username", sa.Text()),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_test_at", sa.Integer()),
        sa.Column("last_test_result", sa.Text()),
        sa.Column("last_test_message", sa.Text()),
        sa.Column("last_test_version", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("auth_type IN ('none','basic')", name="ck_endpoints_auth_type"),
    )
    op.create_index("ux_endpoints_name", "endpoints", [sa.text("name COLLATE NOCASE")], unique=True)
    op.create_index(
        "ux_endpoints_default", "endpoints", ["is_default"], unique=True, sqlite_where=sa.text("is_default = 1")
    )
    op.create_index("ix_endpoints_enabled", "endpoints", ["enabled"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("endpoint_id", sa.Text(), sa.ForeignKey("endpoints.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("working_directory", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_variant", sa.Text()),
        sa.Column("agent", sa.Text()),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="enabled"),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("schedule_type", sa.Text(), nullable=False, server_default="none"),
        sa.Column("cron_expression", sa.Text()),
        sa.Column("run_at", sa.Integer()),
        sa.Column("interval_seconds", sa.Integer()),
        sa.Column("overlap_policy", sa.Text(), nullable=False, server_default="queue"),
        sa.Column("missed_policy", sa.Text(), nullable=False, server_default="skip"),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("next_run_at", sa.Integer()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.Integer()),
        sa.CheckConstraint("status IN ('enabled','disabled','archived')", name="ck_tasks_status"),
        sa.CheckConstraint("schedule_type IN ('none','cron','once','interval')", name="ck_tasks_schedule_type"),
        sa.CheckConstraint("overlap_policy IN ('queue','skip')", name="ck_tasks_overlap"),
        sa.CheckConstraint("missed_policy IN ('skip','run_once')", name="ck_tasks_missed"),
        sa.CheckConstraint("timeout_minutes BETWEEN 1 AND 10080", name="ck_tasks_timeout"),
    )
    op.create_index("ix_tasks_schedulable", "tasks", ["status", "schedule_enabled", "next_run_at"])
    op.create_index("ix_tasks_endpoint", "tasks", ["endpoint_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("trigger_source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("occurrence_key", sa.Text()),
        sa.Column("scheduled_for", sa.Integer()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.Integer()),
        sa.Column("started_at", sa.Integer()),
        sa.Column("submitting_at", sa.Integer()),
        sa.Column("running_at", sa.Integer()),
        sa.Column("finished_at", sa.Integer()),
        sa.Column("deadline_at", sa.Integer()),
        sa.Column("cancel_requested_at", sa.Integer()),
        sa.Column("cancel_confirmed_at", sa.Integer()),
        sa.Column("cancel_reason", sa.Text()),
        sa.Column("last_heartbeat_at", sa.Integer()),
        sa.Column("task_name_snapshot", sa.Text(), nullable=False),
        sa.Column("endpoint_id", sa.Text(), sa.ForeignKey("endpoints.id", ondelete="SET NULL")),
        sa.Column("endpoint_name_snapshot", sa.Text(), nullable=False),
        sa.Column("endpoint_url_snapshot", sa.Text(), nullable=False),
        sa.Column("endpoint_auth_type_snapshot", sa.Text(), nullable=False),
        sa.Column("working_directory", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_variant", sa.Text()),
        sa.Column("agent", sa.Text()),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("utc_offset", sa.Text(), nullable=False),
        sa.Column("schedule_summary", sa.Text(), nullable=False),
        sa.Column("overlap_policy", sa.Text(), nullable=False),
        sa.Column("missed_policy", sa.Text(), nullable=False),
        sa.Column("timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("opencode_session_id", sa.Text()),
        sa.Column("opencode_session_title", sa.Text()),
        sa.Column("final_response", sa.Text()),
        sa.Column("final_response_truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_phase", sa.Text()),
        sa.Column("error_type", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("trace_integrity", sa.Text()),
        sa.Column("trace_gap_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("reasoning_tokens", sa.Integer()),
        sa.Column("cache_read_tokens", sa.Integer()),
        sa.Column("cache_write_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Float()),
        sa.Column("rerun_of_run_id", sa.Text(), sa.ForeignKey("runs.id", ondelete="SET NULL")),
        sa.Column("config_snapshot_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("trigger_source IN ('scheduled','manual','rerun','recovery')", name="ck_runs_source"),
        sa.CheckConstraint(
            f"status IN ({','.join(repr(item) for item in RUN_STATUSES)})", name="ck_runs_status"
        ),
        sa.CheckConstraint("overlap_policy IN ('queue','skip')", name="ck_runs_overlap"),
        sa.CheckConstraint("missed_policy IN ('skip','run_once')", name="ck_runs_missed"),
    )
    op.create_index(
        "ux_runs_task_occurrence",
        "runs",
        ["task_id", "occurrence_key"],
        unique=True,
        sqlite_where=sa.text("occurrence_key IS NOT NULL"),
    )
    op.create_index(
        "ux_runs_session",
        "runs",
        ["opencode_session_id"],
        unique=True,
        sqlite_where=sa.text("opencode_session_id IS NOT NULL"),
    )
    op.create_index("ix_runs_task_created", "runs", ["task_id", sa.text("created_at DESC")])
    op.create_index("ix_runs_status_created", "runs", ["status", sa.text("created_at DESC")])
    op.create_index("ix_runs_endpoint_created", "runs", ["endpoint_id", sa.text("created_at DESC")])
    op.create_index("ix_runs_scheduled_for", "runs", ["scheduled_for"])

    op.create_table(
        "run_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.Integer(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text()),
        sa.CheckConstraint("level IN ('info','warn','error')", name="ck_run_logs_level"),
    )
    op.create_index("ix_run_logs_run_at", "run_logs", ["run_id", "at"])

    op.create_table(
        "trace_items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("parent_external_id", sa.Text()),
        sa.Column("name", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer()),
        sa.Column("ended_at", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("input_json", sa.Text()),
        sa.Column("output_text", sa.Text()),
        sa.Column("error_text", sa.Text()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('user_message','assistant_message','tool','skill','file','permission','error','system')",
            name="ck_trace_kind",
        ),
    )
    op.create_index("ux_trace_run_kind_external", "trace_items", ["run_id", "kind", "external_id"], unique=True)
    op.create_index("ix_trace_run_sequence", "trace_items", ["run_id", "sequence"])
    op.create_index("ix_trace_run_started", "trace_items", ["run_id", "started_at"])


def downgrade() -> None:
    op.drop_table("trace_items")
    op.drop_table("run_logs")
    op.drop_table("runs")
    op.drop_table("tasks")
    op.drop_index("ix_endpoints_enabled", table_name="endpoints")
    op.drop_index("ux_endpoints_default", table_name="endpoints")
    op.drop_index("ux_endpoints_name", table_name="endpoints")
    op.drop_table("endpoints")
