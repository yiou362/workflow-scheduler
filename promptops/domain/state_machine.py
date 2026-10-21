"""Run state machine.

Every status write must go through this module (or the repository conditional
update helper that uses it); terminal states are irreversible and ``Cancelled``
/ ``Timeout`` may only be written after the stop is confirmed.
"""

from __future__ import annotations

from promptops.enums import (
    ACTIVE_RUN_STATUSES,
    PENDING_OR_ACTIVE_STATUSES,
    TERMINAL_RUN_STATUSES,
    CancelReason,
    RunStatus,
)

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.PREPARING, RunStatus.CANCELLED, RunStatus.SKIPPED}),
    RunStatus.PREPARING: frozenset(
        {
            RunStatus.SUBMITTING,
            RunStatus.FAILED,
            RunStatus.SKIPPED,
            RunStatus.CANCELLING,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
    ),
    RunStatus.SUBMITTING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.FAILED,
            RunStatus.UNKNOWN,
            RunStatus.CANCELLING,
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
        }
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.UNKNOWN,
        }
    ),
    RunStatus.WAITING: frozenset(
        {
            RunStatus.RUNNING,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLING,
            RunStatus.UNKNOWN,
        }
    ),
    RunStatus.CANCELLING: frozenset(
        {
            RunStatus.CANCELLED,
            RunStatus.TIMEOUT,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.UNKNOWN,
        }
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.TIMEOUT: frozenset(),
    RunStatus.SKIPPED: frozenset(),
    RunStatus.UNKNOWN: frozenset(),
}


class InvalidTransition(RuntimeError):
    def __init__(self, source: RunStatus | str, target: RunStatus | str) -> None:
        super().__init__(f"illegal run transition: {source} -> {target}")
        self.source = str(source)
        self.target = str(target)


def as_status(value: RunStatus | str) -> RunStatus:
    return value if isinstance(value, RunStatus) else RunStatus(value)


def can_transition(source: RunStatus | str, target: RunStatus | str) -> bool:
    source_status = as_status(source)
    target_status = as_status(target)
    return target_status in ALLOWED_TRANSITIONS[source_status]


def ensure_transition(source: RunStatus | str, target: RunStatus | str) -> None:
    if not can_transition(source, target):
        raise InvalidTransition(source, target)


def is_active(status: RunStatus | str) -> bool:
    return as_status(status) in ACTIVE_RUN_STATUSES


def is_pending_or_active(status: RunStatus | str) -> bool:
    return as_status(status) in PENDING_OR_ACTIVE_STATUSES


def is_terminal(status: RunStatus | str) -> bool:
    return as_status(status) in TERMINAL_RUN_STATUSES


def status_for_outcome(
    outcome: str | None,
    *,
    cancel_reason: CancelReason | str | None = None,
) -> RunStatus | None:
    """Map an OpenCode session ``outcome`` to a Run terminal status.

    ``None`` means the session is still active (no outcome reported).
    """

    if outcome == "succeeded":
        return RunStatus.COMPLETED
    if outcome == "failed":
        return RunStatus.FAILED
    if outcome == "interrupted":
        if cancel_reason == CancelReason.TIMEOUT or cancel_reason == "timeout":
            return RunStatus.TIMEOUT
        if cancel_reason == CancelReason.USER or cancel_reason == "user":
            return RunStatus.CANCELLED
        return RunStatus.FAILED
    return None


def status_after_terminal_event(event_type: str, *, cancel_reason: str | None = None) -> RunStatus:
    """Map ``session.execution.*`` terminal events to a status."""

    if event_type.endswith("succeeded"):
        return RunStatus.COMPLETED
    if event_type.endswith("failed"):
        return RunStatus.FAILED
    if event_type.endswith("interrupted"):
        if cancel_reason == "user":
            return RunStatus.CANCELLED
        if cancel_reason == "timeout":
            return RunStatus.TIMEOUT
        return RunStatus.FAILED
    raise ValueError(f"not a terminal execution event: {event_type}")


def error_type_for_terminal_event(event_type: str, cancel_reason: str | None) -> str | None:
    if event_type.endswith("failed"):
        return "session_failed"
    if event_type.endswith("interrupted") and cancel_reason not in ("user", "timeout"):
        return "remote_interrupted"
    return None
