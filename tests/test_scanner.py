from __future__ import annotations

import os
from pathlib import Path

import pytest

from dustbunny.scanner import discover, tree_stats, validate_roots


def make_tree(root: Path) -> None:
    (root / "app" / "config").mkdir(parents=True)
    (root / "app" / "config" / "db").write_bytes(b"x" * 10_000)
    (root / "empty").mkdir()
    (root / "file.txt").write_text("not a folder")
    (root / "link").symlink_to(root / "app")


def test_discover_lists_direct_subfolders(tmp_path: Path) -> None:
    make_tree(tmp_path)
    result = discover([str(tmp_path)])
    by_name = {c.name: c for c in result.candidates}
    assert set(by_name) == {"app", "empty", "link"}
    assert by_name["app"].path == f"{tmp_path}/app"
    assert by_name["app"].root == str(tmp_path)
    assert by_name["app"].size_bytes >= 10_000
    assert by_name["app"].last_modified is not None
    assert by_name["link"].is_symlink
    assert by_name["link"].size_bytes is None
    assert not by_name["app"].is_mountpoint
    assert not result.warnings


def test_discover_without_stats(tmp_path: Path) -> None:
    make_tree(tmp_path)
    result = discover([str(tmp_path)], with_stats=False)
    assert all(c.size_bytes is None for c in result.candidates)


def test_discover_missing_root_warns(tmp_path: Path) -> None:
    result = discover([str(tmp_path / "missing")])
    assert result.candidates == []
    assert result.warnings[0].code == "root-missing"


def test_symlinked_root_exposes_real_path(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "sonarr").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    (candidate,) = discover([str(alias)]).candidates
    assert candidate.path == f"{alias}/sonarr"
    assert candidate.real_path == f"{real}/sonarr"


def test_tree_stats_newest_mtime_and_hardlinks(tmp_path: Path) -> None:
    folder = tmp_path / "f"
    (folder / "sub").mkdir(parents=True)
    data = folder / "sub" / "data"
    data.write_bytes(b"y" * 50_000)
    os.link(data, folder / "hardlink")
    os.utime(folder, (1_000_000, 1_000_000))
    os.utime(data, (2_000_000_000, 2_000_000_000))

    stats = tree_stats(str(folder))
    assert stats.complete
    assert stats.newest == 2_000_000_000
    single = tree_stats(str(folder / "sub")).size
    # The hard-linked file is counted only once.
    assert stats.size < single + 50_000


def test_tree_stats_measures_requested_parts(tmp_path: Path) -> None:
    (tmp_path / "config" / "cache").mkdir(parents=True)
    (tmp_path / "config" / "cache" / "big").write_bytes(b"c" * 200_000)
    (tmp_path / "config" / "settings.xml").write_bytes(b"s" * 20_000)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "x").write_bytes(b"o" * 80_000)
    parts = [f"{tmp_path}/config", f"{tmp_path}/config/cache", f"{tmp_path}/config/settings.xml"]

    stats = tree_stats(str(tmp_path), [*parts, f"{tmp_path}/missing"])
    cache = tree_stats(str(tmp_path / "config" / "cache")).size
    config = tree_stats(str(tmp_path / "config")).size
    assert stats.parts[f"{tmp_path}/config/cache"] == cache
    assert stats.parts[f"{tmp_path}/config"] == config  # nested parts count in both
    assert 20_000 <= stats.parts[f"{tmp_path}/config/settings.xml"] < 40_000
    assert f"{tmp_path}/missing" not in stats.parts
    assert stats.size > config + 80_000


def test_discover_measures_tracked_paths(tmp_path: Path) -> None:
    make_tree(tmp_path)
    tracked = {f"{tmp_path}/app/config", f"{tmp_path}/link/config/db", "/elsewhere/x"}
    (app, empty, link) = discover([str(tmp_path)], tracked=tracked).candidates
    # a path through the symlink is measured in the folder it points to, as the
    # matcher reads it there
    assert set(app.path_sizes) == {f"{tmp_path}/app/config", f"{tmp_path}/app/config/db"}
    assert app.path_sizes[f"{tmp_path}/app/config"] >= 10_000
    assert empty.path_sizes == {} and link.path_sizes == {}
    unmeasured = discover([str(tmp_path)], with_stats=False, tracked=tracked).candidates
    assert unmeasured[0].path_sizes == {}


def test_discover_measures_paths_of_a_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "sonarr" / "config").mkdir(parents=True)
    (real / "sonarr" / "config" / "db").write_bytes(b"d" * 30_000)
    alias = tmp_path / "alias"
    alias.symlink_to(real)
    tracked = {f"{real}/sonarr/config", f"{alias}/sonarr/config"}
    (candidate,) = discover([str(alias)], tracked=tracked).candidates
    assert candidate.path_sizes[f"{real}/sonarr/config"] >= 30_000
    assert candidate.path_sizes[f"{alias}/sonarr/config"] >= 30_000


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_tree_stats_unreadable_is_incomplete(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        assert tree_stats(str(tmp_path)).complete is False
    finally:
        locked.chmod(0o755)


def test_validate_roots() -> None:
    assert validate_roots(["/opt/appdata/", " /srv ", "/opt/appdata"]) == [
        "/opt/appdata",
        "/srv",
    ]
    for bad in (["relative"], ["/"], [], [" "]):
        with pytest.raises(ValueError):
            validate_roots(bad)


def test_created_date(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (candidate,) = discover([str(tmp_path)], with_stats=False).candidates
    # most local file systems record it; network shares don't (then it's None)
    if candidate.created is not None:
        import time

        assert abs(candidate.created.timestamp() - time.time()) < 120
