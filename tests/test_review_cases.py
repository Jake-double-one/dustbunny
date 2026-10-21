"""Cases from the plausibility review: each one once made a live folder look
orphaned, crashed a scan or sent a wrong notification."""

from __future__ import annotations

from pathlib import Path

from dustbunny.collectors.base import CollectorResult
from dustbunny.config import Settings
from dustbunny.i18n import warning
from dustbunny.matcher import build_report, classify
from dustbunny.models import Candidate, Category, Reference, RefState, SourceStatus
from dustbunny.scanner import discover
from dustbunny.service import ScanService, without_own_root_mounts
from dustbunny.state import State

ROOT = "/opt/appdata"


def ref(path: str, owner: str = "c", **kw) -> Reference:
    return Reference(path=path, source="docker", state=RefState.RUNNING, owner=owner, **kw)


def test_symlink_in_root_protects_its_target(tmp_path: Path) -> None:
    root = tmp_path / "appdata"
    (root / "sonarr-v4").mkdir(parents=True)
    (root / "sonarr").symlink_to("sonarr-v4")
    candidates = discover([str(root)], with_stats=False).candidates
    link = next(c for c in candidates if c.name == "sonarr")
    assert link.link_target == f"{root}/sonarr-v4"
    results = classify(candidates, [ref(f"{root}/sonarr/config")], roots=[str(root)])
    by_name = {r.name: r for r in results}
    assert by_name["sonarr-v4"].category is Category.ACTIVE
    assert by_name["sonarr"].category is Category.IGNORED
    assert by_name["sonarr"].reasons[0].params["target"] == f"{root}/sonarr-v4"


def test_own_container_keeps_its_data_folder() -> None:
    refs = [
        ref(ROOT, owner="dustbunny"),  # mounts the whole root: noise, dropped
        ref(f"{ROOT}/dustbunny", owner="dustbunny"),  # its /data: kept
        ref(ROOT, owner="duplicati"),  # someone else's broad mount: kept
    ]
    kept = without_own_root_mounts(refs, [ROOT], {"dustbunny"})
    assert [(r.owner, r.path) for r in kept] == [
        ("dustbunny", f"{ROOT}/dustbunny"),
        ("duplicati", ROOT),
    ]


def test_failed_root_makes_report_incomplete() -> None:
    report = build_report(
        [Candidate(path=f"{ROOT}/a", root=ROOT, name="a")],
        [],
        roots=[ROOT, "/srv/other"],
        sources=[SourceStatus(name="docker")],
        failed_roots=["/srv/other"],
    )
    assert not report.complete and not report.reliable


def test_uncertain_warning_blocks_notifications() -> None:
    report = build_report(
        [Candidate(path=f"{ROOT}/a", root=ROOT, name="a")],
        [ref(f"{ROOT}/b")],
        roots=[ROOT],
        sources=[
            SourceStatus(
                name="portainer",
                warnings=[warning("compose-unresolved-volume", file="x", detail="y", path="$A")],
            )
        ],
    )
    assert report.complete and report.uncertain and not report.reliable


class _Refs:
    name = "docker"

    def __init__(self, refs, ok=True):
        self.refs, self.ok = refs, ok

    def collect(self) -> CollectorResult:
        return CollectorResult(references=self.refs, error=None if self.ok else "down")


def service(tmp_path: Path, collectors, sent):
    root = tmp_path / "appdata"
    settings = Settings(
        scan_roots=[str(root)],
        data_dir=tmp_path / "data",
        docker_enabled=False,
        notify_urls=["json://localhost"],
    )
    return root, ScanService(
        settings,
        State(settings.data_dir / "db.sqlite3"),
        collectors=lambda: collectors,
        sender=lambda urls, title, body: sent.append(title) or True,
    )


def test_notifications_first_scan_new_and_never_when_incomplete(tmp_path: Path) -> None:
    sent: list[str] = []
    collector = _Refs([])
    root, svc = service(tmp_path, [collector], sent)
    (root / "a").mkdir(parents=True)
    svc.scan()
    assert sent == ["Dustbunny: 1 orphaned folder found"]
    (root / "b").mkdir()
    svc.scan()
    assert sent[-1] == "Dustbunny: 1 new orphaned folder"
    collector.ok = False
    (root / "c").mkdir()
    svc.scan()
    assert len(sent) == 2  # incomplete: silent
    assert svc.report and not svc.report.complete


def test_missing_root_does_not_resolve_orphans(tmp_path: Path) -> None:
    sent: list[str] = []
    root, svc = service(tmp_path, [_Refs([])], sent)
    (root / "a").mkdir(parents=True)
    first = svc.scan()
    assert first and first.folders[0].first_seen
    since = first.folders[0].first_seen
    (root / "a").rename(tmp_path / "moved")  # root now empty, e.g. not mounted
    svc.scan()
    (tmp_path / "moved").rename(root / "a")
    third = svc.scan()
    assert third and third.folders[0].first_seen == since
    assert sent == ["Dustbunny: 1 orphaned folder found"]


def test_ignore_works_after_restart(tmp_path: Path) -> None:
    root, svc = service(tmp_path, [_Refs([])], [])
    (root / "a").mkdir(parents=True)
    svc.scan()
    restarted = ScanService(svc.settings, State(svc.settings.data_dir / "db.sqlite3"))
    report = restarted.set_ignored(f"{root}/a", True)
    assert report.folders[0].category is Category.IGNORED
