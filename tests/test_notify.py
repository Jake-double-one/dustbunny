from __future__ import annotations

from dustbunny.models import Category
from dustbunny.notify import build_message, format_size, send
from dustbunny.state import OrphanChanges
from tests.test_state import report


def test_new_orphans_message() -> None:
    rep = report(["a", "b"])
    changes = OrphanChanges(new=list(rep.folders))
    title, body = build_message(rep, changes, mode="change", lang="en")
    assert title == "Dustbunny: 2 new orphaned folders"
    assert "/opt/appdata/a" in body and "Orphaned now: 2 folders" in body


def test_german_and_resolved() -> None:
    rep = report(["a"], refs=["a"])
    changes = OrphanChanges(resolved=[("/opt/appdata/a", rep.folders[0]), ("/opt/appdata/z", None)])
    title, body = build_message(rep, changes, mode="change", lang="de")
    assert title == "Dustbunny: 2 Ordner sind nicht mehr verwaist"
    assert "/opt/appdata/a (Aktiv)" in body and "/opt/appdata/z (entfernt)" in body
    assert format_size(1536, "de") == "1,5 KiB" and format_size(1536) == "1.5 KiB"
    assert rep.folders[0].category is Category.ACTIVE


def test_no_message_without_change_or_when_incomplete() -> None:
    rep = report(["a"])
    assert build_message(rep, OrphanChanges(), mode="change", lang="en") is None
    title, _ = build_message(rep, OrphanChanges(), mode="always", lang="en")
    assert title == "Dustbunny: 1 orphaned folder"
    broken = report(["a"], ok=False)
    assert (
        build_message(broken, OrphanChanges(new=broken.folders), mode="always", lang="en") is None
    )


def test_send_without_urls() -> None:
    assert send([], "t", "b") is False


def test_send_with_bad_url() -> None:
    assert send(["not-a-real-scheme://x"], "t", "b") is False
