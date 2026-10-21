from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from dustbunny.matcher import build_report
from dustbunny.models import Candidate, Category, Reference, RefState, SourceStatus
from dustbunny.state import State

ROOT = "/opt/appdata"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def report(names, refs=(), *, ok=True, at=T0, ignored=()):
    candidates = [Candidate(path=f"{ROOT}/{n}", root=ROOT, name=n) for n in names]
    references = [
        Reference(path=f"{ROOT}/{r}", source="docker", state=RefState.RUNNING) for r in refs
    ]
    rep = build_report(
        candidates,
        references,
        roots=[ROOT],
        sources=[SourceStatus(name="docker", ok=ok, error=None if ok else "down")],
        ignored_paths=ignored,
    )
    rep.generated_at = at
    return rep


def test_first_seen_and_changes(tmp_path: Path) -> None:
    state = State(tmp_path / "db.sqlite3")
    first = report(["a", "b"], refs=["a"])
    changes = state.track_orphans(first)
    assert changes.first_scan
    assert [f.name for f in changes.new] == ["b"]
    assert first.folders[0].first_seen == T0

    later = T0 + timedelta(days=3)
    second = report(["a", "b", "c"], refs=["a"], at=later)
    changes = state.track_orphans(second)
    assert not changes.first_scan
    assert [f.name for f in changes.new] == ["c"]
    seen = {f.name: f.first_seen for f in second.folders if f.category is Category.ORPHAN}
    assert seen == {"b": T0, "c": later}  # b keeps its original date

    third = report(["a", "b"], refs=["a", "b"], at=later)  # b in use again, c deleted
    changes = state.track_orphans(third)
    resolved = {path: (f.category if f else None) for path, f in changes.resolved}
    assert resolved == {f"{ROOT}/b": Category.ACTIVE, f"{ROOT}/c": None}


def test_incomplete_report_changes_nothing(tmp_path: Path) -> None:
    state = State(tmp_path / "db.sqlite3")
    state.track_orphans(report(["a", "b"]))
    broken = report(["a"], ok=False, at=T0 + timedelta(days=1))
    changes = state.track_orphans(broken)
    assert not changes.changed
    assert broken.folders[0].first_seen == T0  # still known from before
    again = report(["a", "b"], at=T0 + timedelta(days=2))
    assert not state.track_orphans(again).changed


def test_ignores_and_report_roundtrip(tmp_path: Path) -> None:
    state = State(tmp_path / "db.sqlite3")
    state.set_ignored(f"{ROOT}/a", True)
    state.set_ignored(f"{ROOT}/a", True)
    assert state.ignored_paths() == {f"{ROOT}/a"}
    state.set_ignored(f"{ROOT}/a", False)
    assert state.ignored_paths() == set()

    assert state.load_report() is None
    rep = report(["x"])
    state.save_report(rep)
    assert State(tmp_path / "db.sqlite3").load_report() == rep
