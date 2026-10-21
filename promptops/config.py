"""Application configuration (pydantic-settings).

All settings are read from environment variables with the ``PROMPTOPS_`` prefix
(and an optional ``.env`` file).  Every other module receives a ``Settings``
instance explicitly so tests can build isolated configurations.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class Settings(BaseSettings):
    """Runtime settings for the whole application."""

    model_config = SettingsConfigDict(
        env_prefix="PROMPTOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path("data")
    database_url: str | None = None
    secret_key: str | None = None
    auto_migrate: bool = True
    utc_offset: str = "+08:00"

    max_concurrent_runs: int = Field(default=2, ge=1, le=32)
    scheduler_tick_seconds: float = Field(default=1.0, gt=0)
    missed_grace_seconds: int = Field(default=300, ge=0)
    cancel_confirm_seconds: int = Field(default=30, ge=1)
    run_heartbeat_seconds: int = Field(default=10, ge=1)
    stale_run_seconds: int = Field(default=300, ge=1)
    sse_stale_seconds: int = Field(default=10, ge=1)
    sse_reconnect_base_ms: int = Field(default=1000, ge=100)
    sse_reconnect_max_ms: int = Field(default=30000, ge=1000)
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    http_read_timeout_seconds: float = Field(default=30.0, gt=0)
    prompt_read_timeout_seconds: float = Field(default=60.0, gt=0)
    max_trace_text_bytes: int = Field(default=262144, ge=1024)
    max_message_pages: int = Field(default=20, ge=1)
    shutdown_grace_seconds: int = Field(default=20, ge=0)

    log_level: str = "INFO"
    log_dir: Path = Path("data/logs")
    frontend_dist: Path = Path("frontend/dist")
    cors_origins: str = ""

    default_endpoint_name: str | None = None
    default_endpoint_url: str | None = None
    default_endpoint_username: str = "opencode"
    default_endpoint_password: str | None = None

    @field_validator("utc_offset")
    @classmethod
    def _validate_offset(cls, value: str) -> str:
        match = _OFFSET_RE.match(value or "")
        if not match:
            raise ValueError("UTC offset must look like +HH:MM or -HH:MM")
        sign, hours, minutes = match.groups()
        if int(hours) > 14 or int(minutes) > 59:
            raise ValueError("UTC offset is out of range")
        return value

    @property
    def data_path(self) -> Path:
        return self.data_dir

    @property
    def logs_path(self) -> Path:
        # ``log_dir`` is kept as given; when it equals the default it follows data_dir.
        if self.log_dir == Path("data/logs") and self.data_dir != Path("data"):
            return self.data_dir / "logs"
        return self.log_dir

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = (self.data_dir / "promptops.db").resolve()
        return "sqlite+aiosqlite:///" + db_path.as_posix()

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (env based)."""

    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
