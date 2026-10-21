from __future__ import annotations

import pytest

from dustbunny.paths import apply_aliases, is_under, normalize, parse_aliases


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/opt/appdata/", "/opt/appdata"),
        ("//opt//appdata/./x/../y", "/opt/appdata/y"),
        ("/", "/"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_is_under() -> None:
    assert is_under("/opt/appdata/x", "/opt/appdata")
    assert not is_under("/opt/appdata", "/opt/appdata")
    assert not is_under("/opt/appdata-old/x", "/opt/appdata")
    assert is_under("/opt", "/")


def test_aliases() -> None:
    aliases = parse_aliases(["/mnt/ssd/appdata=/opt/appdata", "/mnt/user=/mnt/union"])
    assert apply_aliases("/mnt/ssd/appdata/sonarr", aliases) == "/opt/appdata/sonarr"
    assert apply_aliases("/mnt/ssd/appdata", aliases) == "/opt/appdata"
    assert apply_aliases("/mnt/ssd/appdata2", aliases) == "/mnt/ssd/appdata2"
    assert apply_aliases("/srv/x", aliases) == "/srv/x"


def test_aliases_longest_prefix_wins() -> None:
    aliases = parse_aliases(["/mnt=/a", "/mnt/ssd=/b"])
    assert apply_aliases("/mnt/ssd/x", aliases) == "/b/x"
    assert apply_aliases("/mnt/hdd/x", aliases) == "/a/hdd/x"


@pytest.mark.parametrize("bad", ["nonsense", "relative=/x", "/x="])
def test_parse_aliases_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_aliases([bad])
