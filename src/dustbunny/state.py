"""Persistent state in SQLite (``<DATA_DIR>/dustbunny.sqlite3``):

* since when each folder is orphaned ("orphaned for 12 days"),
* folders ignored in the web UI,
* the last report, so the UI has something to show right after a restart.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dustbunny.models import Category, FolderResult, ScanReport

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


@dataclass
class OrphanChanges:
    """Difference to the previous complete scan."""

    new: list[FolderResult] = field(default_factory=list)
    resolved: list[tuple[str, FolderResult | None]] = field(default_factory=list)
    first_scan: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.new or self.resolved)


class State:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.executescript(SCHEMA)

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

    def track_orphans(self, report: ScanReport) -> OrphanChanges:
        """Record orphans of a report and fill in ``first_seen``.

        Only a complete report changes what is recorded: an incomplete one
        (a source failed) would make folders appear and disappear wrongly.
        """
        changes = OrphanChanges()
        orphans = {f.path: f for f in report.folders if f.category is Category.ORPHAN}
        by_path = {f.path: f for f in report.folders}
        with self._connect() as db:
            known = dict(db.execute("SELECT path, since FROM orphans").fetchall())
            changes.first_scan = (
                db.execute("SELECT 1 FROM meta WHERE key = 'tracked'").fetchone() is None
            )
            if report.complete:
                since = report.generated_at.isoformat()
                for path, folder in orphans.items():
                    if path not in known:
                        db.execute("INSERT INTO orphans (path, since) VALUES (?, ?)", (path, since))
                        known[path] = since
                        changes.new.append(folder)
                for path in [p for p in known if p not in orphans]:
                    db.execute("DELETE FROM orphans WHERE path = ?", (path,))
                    del known[path]
                    changes.resolved.append((path, by_path.get(path)))
                db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('tracked', '1')")
        for path, folder in orphans.items():
            if path in known:
                folder.first_seen = datetime.fromisoformat(known[path])
        return changes

    # ---- last report -----------------------------------------------------------

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
