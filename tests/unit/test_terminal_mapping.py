from promptops.domain.state_machine import error_type_for_terminal_event, status_after_terminal_event
from promptops.enums import RunStatus


def test_terminal_mapping_table():
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


def test_error_types_for_terminal_events():
    assert error_type_for_terminal_event("session.execution.failed", None) == "session_failed"
    assert error_type_for_terminal_event("session.execution.interrupted", None) == "remote_interrupted"
    assert error_type_for_terminal_event("session.execution.interrupted", "user") is None
    assert error_type_for_terminal_event("session.execution.interrupted", "timeout") is None
