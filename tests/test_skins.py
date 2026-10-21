from __future__ import annotations

import re
from pathlib import Path

from dustbunny.skins import (
    BUILTIN_DIR,
    TOKENS,
    SkinCache,
    contrast_problems,
    load_skins,
    parse_skin,
)


def test_builtin_skins_are_complete_and_readable(caplog) -> None:
    skins = load_skins()
    assert [s.id for s in skins.skins] == ["dark", "amoled", "light", "mango"]
    assert skins.defaults == {"light": "light", "dark": "dark"}
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    for skin in skins.skins:
        assert sorted(skin.vars) == sorted(TOKENS), skin.id
        assert contrast_problems(skin.vars) == [], skin.id
    light = next(s for s in skins.as_list()["skins"] if s["id"] == "light")
    assert light["names"] == {"": "Light", "de": "Hell"}


def test_parse_refuses_unsafe_values() -> None:
    skin = parse_skin(
        "x",
        "/*\n * name: Ocean\n * name.de: Ozean\n * scheme: dark\n * order: 5\n */\n"
        ":root {\n  --bg: #0B1A2A;\n  --ink: url(evil);\n  --dusk: #12345;\n"
        "  --shadow: 0 0 2px rgba(0,0,0,.4);\n  --position: absolute;\n}\n"
        "body { --surface: #ffffff }",
    )
    assert skin.names == {"": "Ocean", "de": "Ozean"}
    assert (skin.scheme, skin.order) == ("dark", 5)
    assert skin.vars == {"bg": "#0b1a2a", "shadow": "0 0 2px rgba(0,0,0,.4)"}  # not body
    problems = "\n".join(skin.problems)
    assert "--ink" in problems and "--dusk" in problems and "--position" in problems


def test_custom_skins_fill_in_and_replace(tmp_path: Path, caplog) -> None:
    (tmp_path / "ocean.css").write_text(
        "/* name: Ocean\n scheme: dark */\n:root { --bg: #0b1a2a; }"
    )
    (tmp_path / "Bad Name.css").write_text(":root{}")
    (tmp_path / "mango.css").write_text(
        "/* name: Mango light\n scheme: light */\n:root { --bg: #ffffff; --ink: #dddddd; }"
    )
    skins = load_skins(custom_dir=tmp_path)
    by_id = {s.id: s for s in skins.skins}
    assert by_id["ocean"].vars["ink"] == by_id["dark"].vars["ink"]
    assert by_id["mango"].names == {"": "Mango light"}
    log = caplog.text
    assert "Bad Name.css" in log and "low contrast: ink on bg" in log
    assert ":root[data-theme='ocean'] {" in skins.css
    assert not re.search(r"[<>]|url\(", skins.css)


def test_readme_example_is_valid() -> None:
    text = (BUILTIN_DIR / "README.md").read_text()
    css = re.search(r"```css\n([\s\S]*?)```", text).group(1)
    skin = parse_skin("ocean", css)
    assert skin.problems == []
    assert sorted(skin.vars) == sorted(TOKENS)
    assert contrast_problems(skin.vars) == []


def test_html_cannot_break_out_of_the_script_tag(tmp_path: Path) -> None:
    (tmp_path / "evil.css").write_text("/* name: </script><b>x */\n:root { --bg: #000000; }")
    html = load_skins(custom_dir=tmp_path).html()
    assert "</script><b>" not in html


def test_cache_notices_new_files(tmp_path: Path) -> None:
    cache = SkinCache(custom_dir=tmp_path, check_s=0)
    assert "ocean" not in {s.id for s in cache.get().skins}
    (tmp_path / "ocean.css").write_text(
        "/* name: Ocean\n scheme: dark */\n:root { --bg: #0b1a2a; }"
    )
    assert "ocean" in {s.id for s in cache.get().skins}
