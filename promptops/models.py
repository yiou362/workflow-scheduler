"""SQLAlchemy ORM models.

Five tables: endpoints, tasks, runs, run_logs, trace_items.  All instants are
UTC epoch milliseconds (``INTEGER``), booleans are 0/1, enums are TEXT + CHECK.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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


class Endpoint(Base):
    __tablename__ = "endpoints"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    auth_username: Mapped[str | None] = mapped_column(Text)
    secret_ciphertext: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_at: Mapped[int | None] = mapped_column(Integer)
    last_test_result: Mapped[str | None] = mapped_column(Text)
    last_test_message: Mapped[str | None] = mapped_column(Text)
    last_test_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("auth_type IN ('none','basic')", name="ck_endpoints_auth_type"),
        Index("ux_endpoints_name", text("name COLLATE NOCASE"), unique=True),
        Index("ux_endpoints_default", "is_default", unique=True, sqlite_where=text("is_default = 1")),
        Index("ix_endpoints_enabled", "enabled"),
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    endpoint_id: Mapped[str] = mapped_column(
        Text, ForeignKey("endpoints.id", ondelete="RESTRICT"), nullable=False
    )
    working_directory: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_variant: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="enabled")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_type: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    cron_expression: Mapped[str | None] = mapped_column(Text)
    run_at: Mapped[int | None] = mapped_column(Integer)
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    overlap_policy: Mapped[str] = mapped_column(Text, nullable=False, default="queue")
    missed_policy: Mapped[str] = mapped_column(Text, nullable=False, default="skip")
    timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    next_run_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("status IN ('enabled','disabled','archived')", name="ck_tasks_status"),
        CheckConstraint("schedule_type IN ('none','cron','once','interval')", name="ck_tasks_schedule_type"),
        CheckConstraint("overlap_policy IN ('queue','skip')", name="ck_tasks_overlap"),
        CheckConstraint("missed_policy IN ('skip','run_once')", name="ck_tasks_missed"),
        CheckConstraint("timeout_minutes BETWEEN 1 AND 10080", name="ck_tasks_timeout"),
        Index("ix_tasks_schedulable", "status", "schedule_enabled", "next_run_at"),
        Index("ix_tasks_endpoint", "endpoint_id"),
        Index("ix_tasks_status", "status"),
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False)
    trigger_source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_key: Mapped[str | None] = mapped_column(Text)
    scheduled_for: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    queued_at: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[int | None] = mapped_column(Integer)
    submitting_at: Mapped[int | None] = mapped_column(Integer)
    running_at: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[int | None] = mapped_column(Integer)
    deadline_at: Mapped[int | None] = mapped_column(Integer)
    cancel_requested_at: Mapped[int | None] = mapped_column(Integer)
    cancel_confirmed_at: Mapped[int | None] = mapped_column(Integer)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    last_heartbeat_at: Mapped[int | None] = mapped_column(Integer)

    task_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("endpoints.id", ondelete="SET NULL")
    )
    endpoint_name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_url_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_auth_type_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    working_directory: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_variant: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    utc_offset: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_summary: Mapped[str] = mapped_column(Text, nullable=False)
    overlap_policy: Mapped[str] = mapped_column(Text, nullable=False)
    missed_policy: Mapped[str] = mapped_column(Text, nullable=False)
    timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    opencode_session_id: Mapped[str | None] = mapped_column(Text)
    opencode_session_title: Mapped[str | None] = mapped_column(Text)
    final_response: Mapped[str | None] = mapped_column(Text)
    final_response_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_phase: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_integrity: Mapped[str | None] = mapped_column(Text)
    trace_gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)

    rerun_of_run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("runs.id", ondelete="SET NULL"))
    config_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("trigger_source IN ('scheduled','manual','rerun','recovery')", name="ck_runs_source"),
        CheckConstraint(f"status IN ({','.join(repr(item) for item in RUN_STATUSES)})", name="ck_runs_status"),
        CheckConstraint("overlap_policy IN ('queue','skip')", name="ck_runs_overlap"),
        CheckConstraint("missed_policy IN ('skip','run_once')", name="ck_runs_missed"),
        Index(
            "ux_runs_task_occurrence",
            "task_id",
            "occurrence_key",
            unique=True,
            sqlite_where=text("occurrence_key IS NOT NULL"),
        ),
        Index(
            "ux_runs_session",
            "opencode_session_id",
            unique=True,
            sqlite_where=text("opencode_session_id IS NOT NULL"),
        ),
        Index("ix_runs_task_created", "task_id", text("created_at DESC")),
        Index("ix_runs_status_created", "status", text("created_at DESC")),
        Index("ix_runs_endpoint_created", "endpoint_id", text("created_at DESC")),
        Index("ix_runs_scheduled_for", "scheduled_for"),
    )


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("level IN ('info','warn','error')", name="ck_run_logs_level"),
        Index("ix_run_logs_run_at", "run_id", "at"),
    )


class TraceItem(Base):
    __tablename__ = "trace_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[int | None] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_json: Mapped[str | None] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    error_text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('user_message','assistant_message','tool','skill','file','permission','error','system')",
            name="ck_trace_kind",
        ),
        Index("ux_trace_run_kind_external", "run_id", "kind", "external_id", unique=True),
        Index("ix_trace_run_sequence", "run_id", "sequence"),
        Index("ix_trace_run_started", "run_id", "started_at"),
    )
