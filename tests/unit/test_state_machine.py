import pytest

from promptops.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    can_transition,
    ensure_transition,
    is_active,
    is_terminal,
    status_after_terminal_event,
    status_for_outcome,
)
from promptops.enums import RunStatus


def test_every_status_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS) == set(RunStatus)


def test_terminal_states_are_irreversible():
    for terminal in (
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMEOUT,
        RunStatus.SKIPPED,
        RunStatus.UNKNOWN,
    ):
        assert is_terminal(terminal)
        for target in RunStatus:
            assert not can_transition(terminal, target)


def test_active_states_follow_the_spec():
    assert is_active(RunStatus.RUNNING)
    assert is_active(RunStatus.WAITING)
    assert not is_active(RunStatus.QUEUED)
    assert can_transition(RunStatus.QUEUED, RunStatus.PREPARING)
    assert can_transition(RunStatus.RUNNING, RunStatus.WAITING)
    assert can_transition(RunStatus.WAITING, RunStatus.RUNNING)
    assert can_transition(RunStatus.CANCELLING, RunStatus.UNKNOWN)
    assert not can_transition(RunStatus.QUEUED, RunStatus.COMPLETED)


def test_illegal_transition_raises():
    with pytest.raises(InvalidTransition):
        ensure_transition(RunStatus.COMPLETED, RunStatus.RUNNING)


def test_terminal_event_mapping():
    assert status_after_terminal_event("session.execution.succeeded") == RunStatus.COMPLETED
    assert status_after_terminal_event("session.execution.failed") == RunStatus.FAILED
    assert (
        status_after_terminal_event("session.execution.interrupted", cancel_reason="user")
        == RunStatus.CANCELLED
    )
    assert (
        status_after_terminal_event("session.execution.interrupted", cancel_reason="timeout")
        == RunStatus.TIMEOUT
    )
    assert (
        status_after_terminal_event("session.execution.interrupted", cancel_reason=None)
        == RunStatus.FAILED
    )


def test_outcome_mapping_and_active_outcome():
    assert status_for_outcome("succeeded") == RunStatus.COMPLETED
    assert status_for_outcome("failed") == RunStatus.FAILED
    assert status_for_outcome("interrupted", cancel_reason="user") == RunStatus.CANCELLED
    assert status_for_outcome("interrupted", cancel_reason="timeout") == RunStatus.TIMEOUT
    assert status_for_outcome(None) is None
