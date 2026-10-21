from __future__ import annotations

from dustbunny.matcher import build_report, classify
from dustbunny.models import (
    Candidate,
    Category,
    Reference,
    RefState,
    Relation,
    SourceStatus,
)

ROOT = "/opt/appdata"


def cand(name: str, root: str = ROOT, **kwargs) -> Candidate:
    return Candidate(path=f"{root}/{name}", root=root, name=name, **kwargs)


def ref(path: str, state: RefState = RefState.RUNNING, owner: str = "c", **kwargs) -> Reference:
    return Reference(path=path, source="test", state=state, owner=owner, **kwargs)


def one(candidate: Candidate, refs: list[Reference], **kwargs):
    kwargs.setdefault("roots", [ROOT])
    (result,) = classify([candidate], refs, **kwargs)
    return result


def test_exact_mount_is_active() -> None:
    result = one(cand("sonarr"), [ref("/opt/appdata/sonarr")])
    assert result.category is Category.ACTIVE
    assert result.protected_by[0].relation is Relation.EXACT
    assert result.reasons[0].code == "used-running"


def test_subfolder_mount_protects() -> None:
    result = one(cand("radarr"), [ref("/opt/appdata/radarr/config/db.sqlite")])
    assert result.category is Category.ACTIVE
    assert result.protected_by[0].relation is Relation.INSIDE


def test_trailing_slash_and_dots_are_normalized() -> None:
    result = one(cand("radarr"), [ref("/opt/appdata/./radarr/")])
    assert result.category is Category.ACTIVE


def test_similar_prefix_does_not_protect() -> None:
    result = one(cand("app"), [ref("/opt/appdata/app-old"), ref("/opt/appdata/ap")])
    assert result.category is Category.ORPHAN


def test_unreferenced_is_orphan() -> None:
    result = one(cand("old"), [ref("/opt/appdata/sonarr"), ref("/srv/other")])
    assert result.category is Category.ORPHAN
    assert [r.code for r in result.reasons] == ["no-reference"]
    assert not result.protected_by


def test_broad_root_mount_does_not_protect() -> None:
    backup = ref("/opt/appdata", owner="duplicati")
    result = one(cand("old"), [backup])
    assert result.category is Category.ORPHAN
    assert result.broad_access[0].relation is Relation.BROAD
    assert result.broad_access[0].reference.owner == "duplicati"
    assert "broad-access-only" in [r.code for r in result.reasons]


def test_broad_parent_mount_does_not_protect() -> None:
    result = one(cand("old"), [ref("/opt"), ref("/")])
    assert result.category is Category.ORPHAN
    assert len(result.broad_access) == 2


def test_broad_mount_is_shown_next_to_real_protection() -> None:
    result = one(cand("sonarr"), [ref("/opt/appdata"), ref("/opt/appdata/sonarr")])
    assert result.category is Category.ACTIVE
    assert len(result.broad_access) == 1
    assert len(result.protected_by) == 1


def test_best_state_wins() -> None:
    refs = [
        ref("/opt/appdata/x", RefState.DEFINED, owner="stack"),
        ref("/opt/appdata/x/config", RefState.STOPPED, owner="old"),
    ]
    assert one(cand("x"), refs).category is Category.STOPPED
    refs.append(ref("/opt/appdata/x", RefState.RUNNING, owner="new"))
    result = one(cand("x"), refs)
    assert result.category is Category.ACTIVE
    assert "new" in result.reasons[0].message
    assert len(result.protected_by) == 3


def test_stopped_stack_definition_counts_as_defined_only() -> None:
    result = one(cand("paperless"), [ref("/opt/appdata/paperless/data", RefState.DEFINED)])
    assert result.category is Category.DEFINED_ONLY
    assert result.reasons[0].code == "defined-only"


def test_ignore_rules() -> None:
    refs = [ref("/opt/appdata/sonarr")]
    assert one(cand("backup-2024"), refs, ignore=["backup-*"]).category is Category.IGNORED
    assert one(cand("keep"), refs, ignore=["/opt/appdata/keep"]).category is Category.IGNORED
    assert one(cand("keep"), refs, ignore=["*/keep"]).category is Category.IGNORED
    assert one(cand("keep"), refs, ignore=["other"]).category is Category.ORPHAN


def test_ignore_wins_over_reference_but_keeps_hits() -> None:
    result = one(cand("sonarr"), [ref("/opt/appdata/sonarr")], ignore=["sonarr"])
    assert result.category is Category.IGNORED
    assert result.reasons[0].code == "ignore-rule"
    assert result.protected_by


def test_builtin_ignores() -> None:
    for name in ("lost+found", ".quarantine", "@eaDir", ".Trash-1000"):
        result = one(cand(name), [])
        assert result.category is Category.IGNORED, name
        assert result.reasons[0].code == "builtin-ignore"


def test_symlink_candidate_is_ignored() -> None:
    result = one(cand("link", is_symlink=True), [])
    assert result.category is Category.IGNORED
    assert result.reasons[0].code == "symlink"


def test_nested_scan_root_is_ignored() -> None:
    result = one(cand("media"), [], roots=[ROOT, "/opt/appdata/media"])
    assert result.category is Category.IGNORED
    assert result.reasons[0].code == "nested-root"
    result = one(cand("media"), [], roots=[ROOT, "/opt/appdata/media/sub"])
    assert result.category is Category.IGNORED


def test_symlinked_root_matches_real_path() -> None:
    # /opt/appdata -> /mnt/ssd/appdata on the host, Docker reports the real path.
    candidate = cand("sonarr", real_path="/mnt/ssd/appdata/sonarr")
    result = one(candidate, [ref("/mnt/ssd/appdata/sonarr/config")])
    assert result.category is Category.ACTIVE
    assert result.protected_by[0].matched_path == "/mnt/ssd/appdata/sonarr"


def test_path_aliases_translate_host_paths() -> None:
    # Host path differs and isn't visible in the container at all.
    refs = [ref("/mnt/user/appdata/sonarr")]
    assert one(cand("sonarr"), refs).category is Category.ORPHAN
    result = one(cand("sonarr"), refs, aliases={"/mnt/user/appdata": ROOT})
    assert result.category is Category.ACTIVE


def test_unresolved_variable_pattern_protects_by_name() -> None:
    pattern = ref("${DATA}/sonarr/config", RefState.DEFINED, glob="*/sonarr/config")
    result = one(cand("sonarr"), [pattern])
    assert result.category is Category.DEFINED_ONLY
    assert "unresolved-match" in [r.code for r in result.reasons]
    assert result.protected_by[0].relation is Relation.INSIDE

    exact = ref("${DATA}/sonarr", RefState.DEFINED, glob="*/sonarr")
    assert one(cand("sonarr"), [exact]).protected_by[0].relation is Relation.EXACT


def test_unresolved_pattern_does_not_protect_other_names() -> None:
    pattern = ref("${DATA}/sonarr", RefState.DEFINED, glob="*/sonarr")
    assert one(cand("sonarr-old"), [pattern]).category is Category.ORPHAN
    assert one(cand("radarr"), [pattern]).category is Category.ORPHAN


def test_vague_pattern_protects_nothing_but_warns() -> None:
    vague = ref("/opt/appdata/${APP}", RefState.DEFINED, owner="s", glob="/opt/appdata/*")
    candidates = [cand("a"), cand("b")]
    results = classify(candidates, [vague], roots=[ROOT])
    assert all(r.category is Category.ORPHAN for r in results)
    report = build_report(candidates, [vague], roots=[ROOT], sources=[SourceStatus(name="test")])
    unresolved = [w for w in report.warnings if w.code == "unresolved-path"]
    assert unresolved and unresolved[0].params["owner"] == "s"


def test_pattern_with_literal_head_outside_roots_does_not_warn() -> None:
    other = ref("/srv/${X}/data", RefState.DEFINED, glob="/srv/*/data")
    report = build_report(
        [cand("a")],
        [other, ref("/opt/appdata/a")],
        roots=[ROOT],
        sources=[SourceStatus(name="test")],
    )
    assert not report.warnings


def test_mountpoint_and_incomplete_stats_are_noted() -> None:
    result = one(cand("nfs", is_mountpoint=True, stats_complete=False), [])
    codes = [r.code for r in result.reasons]
    assert "mountpoint" in codes
    assert "stats-incomplete" in codes


def test_report_summary_and_order() -> None:
    candidates = [
        cand("active", size_bytes=100),
        cand("orphan1", size_bytes=10),
        cand("orphan2", size_bytes=5),
        cand("lost+found", size_bytes=1),
    ]
    report = build_report(
        candidates,
        [ref("/opt/appdata/active")],
        roots=[ROOT],
        sources=[SourceStatus(name="test", reference_count=1)],
    )
    assert report.complete
    assert [f.name for f in report.folders] == ["orphan1", "orphan2", "active", "lost+found"]
    assert report.summary.total == 4
    assert report.summary.counts[Category.ORPHAN] == 2
    assert report.summary.counts[Category.ACTIVE] == 1
    assert report.summary.counts[Category.IGNORED] == 1
    assert report.summary.orphan_bytes == 15
    assert report.summary.total_bytes == 116
    assert report.folders[0].checked_sources == ["test"]


def test_report_incomplete_when_source_failed() -> None:
    report = build_report(
        [cand("x")],
        [],
        roots=[ROOT],
        sources=[SourceStatus(name="portainer", ok=False, error="timeout")],
    )
    assert not report.complete
    assert report.folders[0].checked_sources == []
    assert report.warnings[0].code == "source-failed"
    assert report.warnings[0].params == {"source": "portainer", "error": "timeout"}


def test_report_incomplete_without_sources() -> None:
    report = build_report([cand("x")], [], roots=[ROOT], sources=[])
    assert not report.complete
    assert [w.code for w in report.warnings] == ["no-sources"]


def test_warns_when_no_reference_points_into_root() -> None:
    # Typical misconfiguration: appdata mounted at /appdata instead of 1:1.
    report = build_report(
        [cand("sonarr", root="/appdata")],
        [ref("/opt/appdata/sonarr")],
        roots=["/appdata"],
        sources=[SourceStatus(name="docker")],
    )
    assert report.folders[0].category is Category.ORPHAN
    assert [w.code for w in report.warnings] == ["root-unreferenced"]
    assert "PATH_ALIASES" in report.warnings[0].message
