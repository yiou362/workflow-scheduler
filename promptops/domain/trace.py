"""Trace helpers: bounded text and OpenCode -> trace status mapping."""

from __future__ import annotations

from promptops.enums import TraceStatus


def truncate_text(value: str | None, max_bytes: int) -> tuple[str | None, bool, int]:
    """Truncate by UTF-8 bytes (never split a codepoint).

    Returns ``(text, truncated, original_bytes)``.
    """

    if value is None:
        return None, False, 0
    encoded = value.encode("utf-8")
    original = len(encoded)
    if original <= max_bytes:
        return value, False, original
    clipped = encoded[:max_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8"), True, original
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return "", True, original


def json_text(value: object) -> str | None:
    """Stable JSON text for trace payload columns (already bounded by caller)."""

    import json

    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


_OPENCODE_TO_TRACE_STATUS = {
    "streaming": TraceStatus.PENDING.value,
    "pending": TraceStatus.PENDING.value,
    "running": TraceStatus.RUNNING.value,
    "completed": TraceStatus.COMPLETED.value,
    "error": TraceStatus.FAILED.value,
    "failed": TraceStatus.FAILED.value,
}


def map_tool_status(status: str | None) -> str:
    return _OPENCODE_TO_TRACE_STATUS.get((status or "").lower(), TraceStatus.INFO.value)


def collapse_content_parts(content: object) -> str:
    """Concatenate ``text`` parts of an OpenCode content array with newlines."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            texts.append(str(part["text"]))
    return "\n".join(texts)
