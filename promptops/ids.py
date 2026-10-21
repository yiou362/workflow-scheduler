"""Identifiers use a short, prefixed UUID so log lines are easy to recognise."""

from __future__ import annotations

import uuid

_PREFIXES = {
    "endpoint": "ep",
    "task": "tsk",
    "run": "run",
    "log": "log",
    "trace": "trc",
}


def new_id(kind: str) -> str:
    prefix = _PREFIXES.get(kind)
    if prefix is None:
        raise ValueError(f"unknown id kind: {kind}")
    return f"{prefix}_{uuid.uuid4().hex[:24]}"
