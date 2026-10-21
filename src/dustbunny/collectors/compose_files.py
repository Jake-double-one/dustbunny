"""References from explicitly listed compose files on the local filesystem."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dustbunny.collectors.base import CollectorResult
from dustbunny.compose_parser import load_compose_file


class ComposeFilesCollector:
    name = "compose-files"

    def __init__(self, files: Sequence[str | Path]):
        self.files = [Path(f) for f in files]

    def collect(self) -> CollectorResult:
        result = CollectorResult()
        for file in self.files:
            parsed = load_compose_file(file, source=self.name)
            result.references.extend(parsed.references)
            result.warnings.extend(f"{file}: {w}" for w in parsed.warnings)
        return result
