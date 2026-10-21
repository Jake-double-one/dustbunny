"""References from compose files on the local filesystem.

``ComposeFilesCollector`` reads explicitly listed files (CLI ``--compose``),
``ComposeDirsCollector`` looks for stacks in ``COMPOSE_DIRS``: compose files
directly in each folder and in its direct subfolders (the layout of Dockge,
Komodo and most hand-made setups: ``/opt/stacks/<stack>/compose.yaml``).

The folders must be mounted under the same path as on the host, otherwise
relative paths in the files resolve to the wrong place.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dustbunny.collectors.base import CollectorResult
from dustbunny.compose_parser import find_compose_files, load_compose_file


class ComposeFilesCollector:
    name = "compose-files"

    def __init__(self, files: Sequence[str | Path]):
        self.files = [Path(f) for f in files]

    def collect(self) -> CollectorResult:
        result = CollectorResult()
        for file in self.files:
            parsed = load_compose_file(file, source=self.name)
            result.references.extend(parsed.references)
            result.warnings.extend(parsed.warnings)
        return result


class ComposeDirsCollector:
    name = "compose-dirs"

    def __init__(self, directories: Sequence[str | Path]):
        self.directories = [Path(d) for d in directories]

    def stack_files(self, directory: Path) -> list[Path]:
        files = find_compose_files(directory)
        for sub in sorted(p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()):
            files.extend(find_compose_files(sub))
        return files

    def collect(self) -> CollectorResult:
        result = CollectorResult()
        missing = [str(d) for d in self.directories if not d.is_dir()]
        for directory in self.directories:
            if not directory.is_dir():
                continue
            for file in self.stack_files(directory):
                parsed = load_compose_file(file, source=self.name)
                result.references.extend(parsed.references)
                result.warnings.extend(parsed.warnings)
        if missing:
            result.error = f"not found: {', '.join(missing)}"
        return result
