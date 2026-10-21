from __future__ import annotations

from pathlib import Path

import pytest

from dustbunny.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the configuration of the machine they run on."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("DOCKER_ENABLED", "false")


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def compose_text():
    def load(name: str) -> str:
        return (FIXTURES / "compose" / name).read_text(encoding="utf-8")

    return load
