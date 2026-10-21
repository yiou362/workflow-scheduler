from promptops.trace.ingestor import compute_final_response, compute_usage_from_messages


def test_last_assistant_text_is_the_final_response():
    messages = [
        {"type": "assistant", "content": [{"type": "text", "text": "intermediate"}]},
        {"type": "assistant", "content": [{"type": "text", "text": "final answer"}]},
    ]
    text, truncated = compute_final_response(messages, 1024)
    assert text == "final answer"
    assert truncated is False


def test_tool_only_last_message_means_no_final_response():
    messages = [
        {"type": "assistant", "content": [{"type": "text", "text": "earlier"}]},
        {"type": "assistant", "content": [{"type": "tool", "id": "c1", "name": "bash"}]},
    ]
    text, truncated = compute_final_response(messages, 1024)
    assert text is None
    assert truncated is False


def test_no_assistant_message():
    assert compute_final_response([{"type": "user", "payload": {"text": "hi"}}], 1024) == (None, False)


def test_empty_text_part_is_not_a_response():
    messages = [{"type": "assistant", "content": [{"type": "text", "text": "   "}]}]
    assert compute_final_response(messages, 1024)[0] is None


def test_final_response_truncation():
    messages = [{"type": "assistant", "content": [{"type": "text", "text": "x" * 5000}]}]
    text, truncated = compute_final_response(messages, 1024)
    assert truncated is True
    assert len(text.encode("utf-8")) <= 1024


def test_usage_from_last_assistant_message():
    messages = [
        {
            "type": "assistant",
            "tokens": {"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 2, "write": 1}},
            "cost": 0.25,
        }
    ]
    usage = compute_usage_from_messages(messages)
    assert usage == {
        "input_tokens": 10,
        "output_tokens": 5,
        "reasoning_tokens": 0,
        "cache_read_tokens": 2,
        "cache_write_tokens": 1,
        "cost_usd": 0.25,
    }


def test_usage_missing_fields_stay_absent():
    assert compute_usage_from_messages([{"type": "assistant"}]) == {}
