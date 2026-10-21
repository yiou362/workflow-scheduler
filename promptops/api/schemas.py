"""Request schemas (Pydantic v2). Responses are plain JSON built by serializers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EndpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    base_url: str = Field(min_length=1)
    auth_type: Literal["none", "basic"] = "none"
    auth_username: str | None = None
    password: str | None = None
    enabled: bool = True
    is_default: bool = False


class EndpointUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    base_url: str | None = None
    auth_type: Literal["none", "basic"] | None = None
    auth_username: str | None = None
    password: str | None = None
    clear_password: bool = False
    enabled: bool | None = None


class EndpointTestRequest(BaseModel):
    endpoint_id: str | None = None
    base_url: str | None = None
    auth_type: Literal["none", "basic"] = "none"
    auth_username: str | None = None
    password: str | None = None


class TaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list)
    endpoint_id: str
    working_directory: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_variant: str | None = None
    agent: str | None = None
    prompt: str
    status: Literal["enabled", "disabled"] = "enabled"
    schedule_enabled: bool = False
    schedule_type: Literal["none", "cron", "once", "interval"] = "none"
    cron_expression: str | None = None
    run_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    overlap_policy: Literal["queue", "skip"] = "queue"
    missed_policy: Literal["skip", "run_once"] = "skip"
    timeout_minutes: int = Field(default=60, ge=1, le=10080)


class TaskCreate(TaskBase):
    pass


class TaskUpdate(TaskBase):
    @field_validator("tags")
    @classmethod
    def _strip_tags(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class SchedulePreviewRequest(BaseModel):
    type: Literal["none", "cron", "once", "interval"] = "none"
    cron: str | None = None
    run_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    count: int = Field(default=5, ge=1, le=10)


class PermissionReplyRequest(BaseModel):
    decision: Literal["once", "always", "reject"]
    message: str | None = None


class RerunRequest(BaseModel):
    endpoint_id: str | None = None
