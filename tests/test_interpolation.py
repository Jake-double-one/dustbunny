from __future__ import annotations

import pytest

from dustbunny.interpolation import interpolate, parse_dotenv
from dustbunny.paths import display, has_unresolved, to_glob

ENV = {"SET": "value", "EMPTY": ""}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "plain"),
        ("$SET", "value"),
        ("${SET}", "value"),
        ("${SET}/x", "value/x"),
        ("pre-$SET-post", "pre-value-post"),
        ("$$SET", "$SET"),
        ("$${SET}", "${SET}"),
        ("${SET:-default}", "value"),
        ("${EMPTY:-default}", "default"),
        ("${NOPE:-default}", "default"),
        ("${EMPTY-default}", ""),
        ("${NOPE-default}", "default"),
        ("${SET:+alt}", "alt"),
        ("${EMPTY:+alt}", ""),
        ("${EMPTY+alt}", "alt"),
        ("${NOPE+alt}", ""),
        ("${NOPE:-${SET}}", "value"),
        ("${NOPE:-${ALSO_NOPE:-deep}/x}", "deep/x"),
        ("costs $5", "costs $5"),
        ("trailing $", "trailing $"),
    ],
)
def test_interpolate_resolved(text: str, expected: str) -> None:
    result = interpolate(text, ENV)
    assert not has_unresolved(result)
    assert result == expected


@pytest.mark.parametrize(
    ("text", "shown", "glob"),
    [
        ("${NOPE}", "${NOPE}", "*"),
        ("$NOPE/x", "$NOPE/x", "*/x"),
        ("${NOPE}/sonarr", "${NOPE}/sonarr", "*/sonarr"),
        ("${NOPE:?required}/a", "${NOPE:?required}/a", "*/a"),
        ("${EMPTY:?required}", "${EMPTY:?required}", "*"),
        ("${NOPE:-${OTHER}}/x", "${OTHER}/x", "*/x"),
    ],
)
def test_interpolate_unresolved_kept_as_marker(text: str, shown: str, glob: str) -> None:
    result = interpolate(text, ENV)
    assert has_unresolved(result)
    assert display(result) == shown
    assert to_glob(result) == glob


def test_parse_dotenv() -> None:
    text = """
    # comment
    export APPDATA=/opt/appdata
    QUOTED="/srv/with space"
    SINGLE='${NOT_EXPANDED}'
    REF=${APPDATA}/sonarr
    INLINE=/opt/x # trailing comment
    ESCAPED="a\\"b"
    not a line
    EMPTY=
    """
    env = parse_dotenv(text)
    assert env == {
        "APPDATA": "/opt/appdata",
        "QUOTED": "/srv/with space",
        "SINGLE": "${NOT_EXPANDED}",
        "REF": "/opt/appdata/sonarr",
        "INLINE": "/opt/x",
        "ESCAPED": 'a"b',
        "EMPTY": "",
    }


def test_parse_dotenv_uses_base_env() -> None:
    env = parse_dotenv("DIR=${BASE}/x", {"BASE": "/data"})
    assert env == {"DIR": "/data/x"}
