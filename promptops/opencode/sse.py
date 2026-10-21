"""Server-Sent Events parsing (``GET /api/event``).

The parser is deliberately small and tolerant: comments/heartbeats are ignored,
multi-line ``data:`` fields are joined with newlines, an ``id:`` field is kept
for ``Last-Event-ID`` reconnects, and a malformed JSON payload is surfaced as a
``SSEMessage`` with ``json_error`` instead of killing the stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, Iterable


@dataclass
class SSEMessage:
    data: str
    event: str | None = None
    id: str | None = None
    json_error: str | None = None

    def json(self) -> dict | None:
        if self.json_error:
            return None
        try:
            value = json.loads(self.data)
        except ValueError:
            self.json_error = "invalid json"
            return None
        return value if isinstance(value, dict) else None


def parse_lines(lines: Iterable[str]) -> Iterable[SSEMessage]:
    """Turn raw text lines into complete SSE messages."""

    data_parts: list[str] = []
    event_name: str | None = None
    event_id: str | None = None
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line == "":
            if data_parts:
                yield SSEMessage(data="\n".join(data_parts), event=event_name, id=event_id)
            data_parts = []
            event_name = None
            event_id = None
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_parts.append(value)
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("id:"):
            event_id = line[3:].strip()
            continue
        if line.startswith("retry:"):
            continue
    if data_parts:
        yield SSEMessage(data="\n".join(data_parts), event=event_name, id=event_id)


async def iter_events(response) -> AsyncIterator[SSEMessage]:  # noqa: ANN001 - httpx.Response
    """Async generator over an httpx streaming response."""

    async for message in _aiter_lines(response):
        yield message


async def _aiter_lines(response) -> AsyncIterator[SSEMessage]:  # noqa: ANN001
    buffer: list[str] = []
    data_parts: list[str] = []
    event_name: str | None = None
    event_id: str | None = None

    def flush() -> SSEMessage | None:
        nonlocal data_parts, event_name, event_id
        if not data_parts:
            return None
        message = SSEMessage(data="\n".join(data_parts), event=event_name, id=event_id)
        data_parts = []
        event_name = None
        event_id = None
        return message

    async for line in response.aiter_lines():
        buffer.append(line)
        if line == "":
            message = flush()
            if message is not None:
                yield message
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            data_parts.append(value)
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("id:"):
            event_id = line[3:].strip()
    message = flush()
    if message is not None:
        yield message
