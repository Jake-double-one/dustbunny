"""Runtime configuration from environment variables (see README)."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CommaList = Annotated[list[str], NoDecode]

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw]?)", re.IGNORECASE)
_DURATION_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(value: str | int | float | timedelta) -> timedelta:
    """``"90"``, ``"30m"``, ``"6h"``, ``"1d12h"`` -> timedelta (bare numbers are seconds)."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, int | float):
        return timedelta(seconds=value)
    text = value.strip().replace(" ", "")
    if not text or not re.fullmatch(r"(\d+[smhdwSMHDW]?)+", text):
        raise ValueError(f"invalid duration {value!r}, use e.g. 30m, 6h or 1d")
    seconds = sum(int(n) * _DURATION_UNITS[unit.lower()] for n, unit in _DURATION_RE.findall(text))
    return timedelta(seconds=seconds)


def split_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]  # type: ignore[union-attr]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False, extra="ignore")

    # what to scan
    scan_roots: CommaList = Field(default_factory=list)
    ignore: CommaList = Field(default_factory=list)
    path_aliases: CommaList = Field(default_factory=list)
    scan_interval: timedelta = timedelta(hours=6)
    scan_sizes: bool = True

    # reference sources
    docker_enabled: bool = True
    portainer_url: str | None = None
    portainer_api_key: SecretStr | None = None
    portainer_endpoint_id: int | None = None
    portainer_insecure: bool = False
    compose_dirs: CommaList = Field(default_factory=list)

    # notifications
    notify_urls: CommaList = Field(default_factory=list)
    notify_on: Literal["change", "always"] = "change"
    notify_language: str = "en"

    # web server
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    auth_user: str | None = None
    auth_password: SecretStr | None = None
    data_dir: Path = Path("/data")
    skins_dir: Path | None = None
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator(
        "scan_roots", "ignore", "path_aliases", "compose_dirs", "notify_urls", mode="before"
    )
    @classmethod
    def _split(cls, value: object) -> list[str]:
        return split_list(value)

    @field_validator("scan_interval", mode="before")
    @classmethod
    def _duration(cls, value: object) -> timedelta:
        return parse_duration(value)  # type: ignore[arg-type]

    @field_validator(
        "portainer_url",
        "portainer_api_key",
        "portainer_endpoint_id",
        "auth_user",
        "auth_password",
        "skins_dir",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        # docker-compose files often carry `VAR: ""` for unused options
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_level", "notify_on", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @property
    def portainer_enabled(self) -> bool:
        return bool(self.portainer_url and self.portainer_api_key)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user and self.auth_password)

    @property
    def custom_skins_dir(self) -> Path:
        return self.skins_dir or self.data_dir / "skins"
