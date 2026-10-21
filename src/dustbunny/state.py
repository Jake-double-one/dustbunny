"""Persistent state in SQLite (``<DATA_DIR>/dustbunny.sqlite3``):

* since when each folder is orphaned ("orphaned for 12 days"),
* folders ignored in the web UI,
* the last report, so the UI has something to show right after a restart.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from dustbunny.models import (
    Candidate,
    Category,
    FolderResult,
    Notice,
    Reference,
    ScanReport,
    SourceStatus,
)
from dustbunny.paths import is_under

SCHEMA = """
CREATE TABLE IF NOT EXISTS orphans (
    path TEXT PRIMARY KEY,
    since TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ignores (
    path TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# scans in a row a root must be empty before its orphans count as removed
EMPTY_SCANS = 3


@dataclass
class OrphanChanges:
    """Difference to the previous complete scan."""

    new: list[FolderResult] = field(default_factory=list)
    resolved: list[tuple[str, FolderResult | None]] = field(default_factory=list)
    first_scan: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.new or self.resolved)


class ScanInputs(BaseModel):
    """What a scan found. Kept (also across restarts) so the report can be
    rebuilt without a new scan when an ignore changes."""

    candidates: list[Candidate]
    references: list[Reference]
    sources: list[SourceStatus]
    warnings: list[Notice] = []
    failed_roots: list[str] = []
    roots: list[str] = []  # the configuration they belong to
    aliases: dict[str, str] = {}


class State:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.executescript(SCHEMA)
        # SQLite creates its file as 0644 whatever the umask is. Group-writable, the same
        # file works whether the container runs as root or as uid 1000 (see Dockerfile).
        with contextlib.suppress(OSError):
            os.chmod(path, os.stat(path).st_mode | 0o060)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            db = sqlite3.connect(self.path)
            try:
                with db:
                    yield db
            finally:
                db.close()

    # ---- ignores ---------------------------------------------------------------

    def ignored_paths(self) -> set[str]:
        with self._connect() as db:
            return {row[0] for row in db.execute("SELECT path FROM ignores")}

    def set_ignored(self, path: str, ignored: bool) -> None:
        with self._connect() as db:
            if ignored:
                db.execute(
                    "INSERT OR IGNORE INTO ignores (path, created_at) VALUES (?, ?)",
                    (path, _now()),
                )
            else:
                db.execute("DELETE FROM ignores WHERE path = ?", (path,))

    # ---- orphans ---------------------------------------------------------------

    def track_orphans(self, report: ScanReport, *, new_scan: bool = True) -> OrphanChanges:
        """Record orphans of a report and fill in ``first_seen``.

        Only a reliable report changes what is recorded: an incomplete or
        uncertain one would make folders appear and disappear wrongly.
        ``new_scan=False`` for a report rebuilt from the same scan (ignore).
        """
        changes = OrphanChanges()
        orphans = {f.path: f for f in report.folders if f.category is Category.ORPHAN}
        by_path = {f.path: f for f in report.folders}
        # A scan root without any folder is more likely not mounted than emptied: its
        # known orphans stay as they are - unless it stays empty for EMPTY_SCANS scans.
        roots_seen = {f.root for f in report.folders}
        with self._connect() as db:
            unseen_roots = []
            for root in report.roots:
                key = f"empty:{root}"
                if root in roots_seen:
                    db.execute("DELETE FROM meta WHERE key = ?", (key,))
                    continue
                row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
                count = int(row[0]) if row else 0
                if new_scan and report.reliable:
                    count += 1
                    db.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(count))
                    )
                if count < EMPTY_SCANS:
                    unseen_roots.append(root)
            known = dict(db.execute("SELECT path, since FROM orphans").fetchall())
            changes.first_scan = (
                db.execute("SELECT 1 FROM meta WHERE key = 'tracked'").fetchone() is None
            )
            if report.reliable:
                since = report.generated_at.isoformat()
                for path, folder in orphans.items():
                    if path not in known:
                        db.execute("INSERT INTO orphans (path, since) VALUES (?, ?)", (path, since))
                        known[path] = since
                        changes.new.append(folder)
                gone = [
                    p
                    for p in known
                    if p not in orphans and not any(is_under(p, r) for r in unseen_roots)
                ]
                for path in gone:
                    db.execute("DELETE FROM orphans WHERE path = ?", (path,))
                    del known[path]
                    changes.resolved.append((path, by_path.get(path)))
                db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('tracked', '1')")
        for path, folder in orphans.items():
            if path in known:
                folder.first_seen = datetime.fromisoformat(known[path])
        return changes

    # ---- last scan -------------------------------------------------------------

    def save_inputs(self, inputs: ScanInputs) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('inputs', ?)",
                (inputs.model_dump_json(),),
            )

    def load_inputs(self) -> ScanInputs | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key = 'inputs'").fetchone()
        if row is None:
            return None
        try:
            return ScanInputs.model_validate_json(row[0])
        except ValueError:
            return None  # written by an incompatible version

    def save_report(self, report: ScanReport) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('report', ?)",
                (report.model_dump_json(),),
            )

    def load_report(self) -> ScanReport | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key = 'report'").fetchone()
        if row is None:
            return None
        try:
            return ScanReport.model_validate_json(row[0])
        except ValueError:
            return None  # written by an incompatible version


def _now() -> str:
    return datetime.now(UTC).isoformat()
