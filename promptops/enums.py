"""Enumerations shared by the domain, persistence, API and executor layers."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum whose ``str()`` is the stored value."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    SUBMITTING = "submitting"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class TaskStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ScheduleType(StrEnum):
    NONE = "none"
    CRON = "cron"
    ONCE = "once"
    INTERVAL = "interval"


class OverlapPolicy(StrEnum):
    QUEUE = "queue"
    SKIP = "skip"


class MissedPolicy(StrEnum):
    SKIP = "skip"
    RUN_ONCE = "run_once"


class TriggerSource(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    RERUN = "rerun"
    RECOVERY = "recovery"


class AuthType(StrEnum):
    NONE = "none"
    BASIC = "basic"


class TraceKind(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL = "tool"
    SKILL = "skill"
    FILE = "file"
    PERMISSION = "permission"
    ERROR = "error"
    SYSTEM = "system"


class TraceStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    APPROVED = "approved"
    INFO = "info"


class TraceIntegrity(StrEnum):
    COMPLETE = "complete"
    GAP = "gap"
    INCOMPLETE = "incomplete"
    NONE = "none"


class EndpointTestResult(StrEnum):
    SUCCESS = "success"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"
    UNSUPPORTED = "unsupported"
    SERVICE_ERROR = "service_error"
    TIMEOUT = "timeout"


class LogLevel(StrEnum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class CancelReason(StrEnum):
    USER = "user"
    TIMEOUT = "timeout"


class ErrorPhase(StrEnum):
    CONNECT = "connect"
    SESSION = "session"
    PROMPT = "prompt"
    STREAM = "stream"
    FINALIZE = "finalize"
    CANCEL = "cancel"
    TIMEOUT = "timeout"
    SCHEDULER = "scheduler"


class PermissionDecision(StrEnum):
    ONCE = "once"
    ALWAYS = "always"
    REJECT = "reject"


ACTIVE_RUN_STATUSES = frozenset(
    {
        RunStatus.PREPARING,
        RunStatus.SUBMITTING,
        RunStatus.RUNNING,
        RunStatus.WAITING,
        RunStatus.CANCELLING,
    }
)

#: "pending or active": used for overlap detection (queued also counts).
PENDING_OR_ACTIVE_STATUSES = frozenset({RunStatus.QUEUED}) | ACTIVE_RUN_STATUSES

TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMEOUT,
        RunStatus.SKIPPED,
        RunStatus.UNKNOWN,
    }
)
