from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def compose_text():
    def load(name: str) -> str:
        return (FIXTURES / "compose" / name).read_text(encoding="utf-8")

    return load
