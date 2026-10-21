from promptops.opencode.sse import parse_lines


def test_multiline_data_and_metadata():
    lines = [
        "event: session.execution.started",
        "id: evt_1",
        "data: {",
        'data:   "type": "session.execution.started"',
        "data: }",
        "",
    ]
    messages = list(parse_lines(lines))
    assert len(messages) == 1
    message = messages[0]
    assert message.event == "session.execution.started"
    assert message.id == "evt_1"
    assert message.json() == {"type": "session.execution.started"}


def test_heartbeat_comments_and_retry_are_ignored():
    lines = [": heartbeat", "retry: 3000", "", "data: {\"id\":\"evt_2\"}", "", ""]
    messages = list(parse_lines(lines))
    assert len(messages) == 1
    assert messages[0].json() == {"id": "evt_2"}


def test_invalid_json_surfaces_error_not_exception():
    messages = list(parse_lines(["data: not-json", ""]))
    assert len(messages) == 1
    assert messages[0].json() is None
    assert messages[0].json_error == "invalid json"


def test_incomplete_message_without_blank_line_flushes():
    messages = list(parse_lines(["data: {\"a\":1}"]))
    assert messages[0].json() == {"a": 1}


def test_message_without_data_is_skipped():
    assert list(parse_lines(["event: x", ""])) == []
