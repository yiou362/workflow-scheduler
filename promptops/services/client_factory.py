"""Build OpenCode clients from stored Endpoint records."""

from __future__ import annotations

from promptops.config import Settings
from promptops.models import Endpoint
from promptops.opencode.client import OpenCodeV2Client
from promptops.security import SecretBox


def client_for_endpoint(
    endpoint: Endpoint, settings: Settings, box: SecretBox
) -> OpenCodeV2Client:
    username: str | None = None
    password = ""
    if endpoint.auth_type == "basic":
        username = endpoint.auth_username or "opencode"
        password = box.decrypt(endpoint.secret_ciphertext) or ""
    return OpenCodeV2Client(
        endpoint.base_url,
        username=username,
        password=password,
        connect_timeout=settings.http_connect_timeout_seconds,
        read_timeout=settings.http_read_timeout_seconds,
        prompt_read_timeout=settings.prompt_read_timeout_seconds,
    )
