"""Secret handling for Endpoint Basic Auth passwords.

Passwords must be recoverable (they are sent to OpenCode), so they are encrypted
with Fernet rather than hashed.  The key comes from ``PROMPTOPS_SECRET_KEY`` or
is generated once at ``<data_dir>/secret.key``.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from promptops.config import Settings


class SecretError(RuntimeError):
    """Raised when the Fernet key is missing, malformed or cannot decrypt."""


def _read_key_file(path: Path) -> bytes:
    try:
        return path.read_bytes().strip()
    except OSError as exc:  # pragma: no cover - depends on filesystem
        raise SecretError(f"cannot read secret key file: {path}") from exc


def load_key(settings: Settings) -> bytes:
    """Load the Fernet key, generating a local key file on first use."""

    if settings.secret_key:
        key = settings.secret_key.encode("utf-8").strip()
        _validate_key(key)
        return key

    path = settings.data_dir / "secret.key"
    if path.exists():
        key = _read_key_file(path)
        _validate_key(key)
        return key

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:  # best effort on POSIX; Windows has no equivalent mode bits
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    return key


def _validate_key(key: bytes) -> None:
    try:
        Fernet(key)
    except (ValueError, TypeError) as exc:
        raise SecretError("PROMPTOPS_SECRET_KEY is not a valid Fernet key") from exc


class SecretBox:
    """Thin wrapper around Fernet with explicit error semantics."""

    def __init__(self, key: bytes) -> None:
        _validate_key(key)
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext == "":
            return None
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str | None:
        if not ciphertext:
            return None
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise SecretError("stored endpoint password cannot be decrypted") from exc


_cache: dict[bytes, SecretBox] = {}


def get_secret_box(settings: Settings) -> SecretBox:
    key = load_key(settings)
    box = _cache.get(key)
    if box is None:
        box = SecretBox(key)
        _cache[key] = box
    return box


def clear_secret_cache() -> None:
    _cache.clear()
