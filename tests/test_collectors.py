from __future__ import annotations

from pathlib import Path

from dustbunny.collectors import CollectorResult, run_collectors
from dustbunny.collectors.static import StaticCollector
from dustbunny.i18n import warning
from dustbunny.matcher import build_report
from dustbunny.models import Candidate, Category, RefState


def test_static_collector(fixtures: Path) -> None:
    result = StaticCollector([fixtures / "references" / "basic.json"]).collect()
    assert len(result.references) == 4
    assert {r.source for r in result.references} == {"static"}
    assert result.references[1].state is RefState.STOPPED


def test_static_references_end_to_end(fixtures: Path) -> None:
    refs, sources = run_collectors([StaticCollector([fixtures / "references" / "basic.json"])])
    names = ["sonarr", "radarr", "old-stack", "forgotten"]
    candidates = [Candidate(path=f"/opt/appdata/{n}", root="/opt/appdata", name=n) for n in names]
    report = build_report(candidates, refs, roots=["/opt/appdata"], sources=sources)
    categories = {f.name: f.category for f in report.folders}
    assert categories == {
        "sonarr": Category.ACTIVE,
        "radarr": Category.STOPPED,
        "old-stack": Category.DEFINED_ONLY,
        "forgotten": Category.ORPHAN,  # the duplicati root mount doesn't protect it
    }
    forgotten = next(f for f in report.folders if f.name == "forgotten")
    assert forgotten.broad_access[0].reference.owner == "duplicati"


class _Failing:
    name = "portainer"

    def collect(self) -> CollectorResult:
        raise ConnectionError("connection refused")


class _Working:
    name = "docker"

    def collect(self) -> CollectorResult:
        return CollectorResult(warnings=[warning("source-failed", source="x", error="y")])


def test_failing_collector_does_not_abort_scan() -> None:
    refs, sources = run_collectors([_Failing(), _Working()])
    assert refs == []
    assert [(s.name, s.ok) for s in sources] == [("portainer", False), ("docker", True)]
    assert sources[0].error == "connection refused"
    assert sources[1].warnings == [warning("source-failed", source="x", error="y")]
