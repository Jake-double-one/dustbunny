"""References from JSON files - for tests, debugging and exotic setups."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from dustbunny.collectors.base import CollectorResult
from dustbunny.models import Reference

_REFERENCES = TypeAdapter(list[Reference])


class StaticCollector:
    """Reads ``[{"path": ..., "state": ...}, ...]`` or ``{"references": [...]}``."""

    name = "static"

    def __init__(self, files: Sequence[str | Path]):
        self.files = [Path(f) for f in files]

    def collect(self) -> CollectorResult:
        result = CollectorResult()
        for file in self.files:
            data = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("references", [])
            for item in data:
                if isinstance(item, dict):
                    item.setdefault("source", self.name)
                    item.setdefault("origin", str(file))
            result.references.extend(_REFERENCES.validate_python(data))
        return result
