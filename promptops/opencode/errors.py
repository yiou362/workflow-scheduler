"""OpenCode v2 errors.

Business code catches these types only; it must not parse raw httpx messages.
Messages never include Authorization headers or passwords.
"""

from __future__ import annotations


class OpenCodeError(Exception):
    """Base class for all OpenCode adapter failures."""

    kind = "opencode_error"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ConnectionFailed(OpenCodeError):
    kind = "connect_unreachable"


class AuthFailed(OpenCodeError):
    kind = "auth_failed"


class UnsupportedServer(OpenCodeError):
    kind = "unsupported"


class HttpError(OpenCodeError):
    kind = "http_error"

    def __init__(self, status: int, body: str = "") -> None:
        snippet = (body or "").strip()[:500]
        super().__init__(
            f"OpenCode returned HTTP {status}" + (f": {snippet}" if snippet else ""), status=status
        )
        self.body = body


class OpenCodeTimeout(OpenCodeError):
    kind = "timeout"


class ProtocolError(OpenCodeError):
    kind = "protocol_error"


class SessionNotFound(HttpError):
    kind = "session_not_found"

    def __init__(self, session_id: str) -> None:
        super().__init__(404, f"session {session_id} not found")
        self.session_id = session_id


class PromptRejected(HttpError):
    kind = "prompt_rejected"


class PromptUncertain(OpenCodeError):
    """Prompt POST outcome is unknown (connection drop / read timeout / 5xx)."""

    kind = "prompt_admission_unknown"


class InterruptUncertain(OpenCodeError):
    kind = "interrupt_unconfirmed"
