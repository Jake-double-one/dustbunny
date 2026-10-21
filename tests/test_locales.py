"""Every language file must match en.json, and every code the backend can
produce must have a text."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dustbunny import i18n
from dustbunny.models import Category, RefState

SRC = Path(i18n.__file__).parent
LOCALES = sorted(i18n.LOCALES_DIR.glob("*.json"))
EN = json.loads((i18n.LOCALES_DIR / "en.json").read_text())


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


@pytest.mark.parametrize("path", LOCALES, ids=lambda p: p.stem)
def test_same_keys_and_placeholders(path: Path) -> None:
    data = json.loads(path.read_text())
    assert set(data) == set(EN), f"{path.name}: keys differ from en.json"
    for key, text in data.items():
        assert isinstance(text, str) and text.strip(), key
        if key != "language.name":
            assert placeholders(text) == placeholders(EN[key]), f"{path.name}: {key}"


def test_backend_codes_have_texts() -> None:
    code = "\n".join(p.read_text() for p in SRC.rglob("*.py"))
    used = {f"reason.{c}" for c in re.findall(r'reason\(\s*"([a-z-]+)"', code)}
    used |= {f"reason.{c}" for c in re.findall(r'RefState\.\w+: "([a-z-]+)"', code)}
    used |= {f"warning.{c}" for c in re.findall(r'warning\(\s*"([a-z-]+)"', code)}
    used |= {f"warning.{c}" for c in re.findall(r'(?:ctx|self)\.warn\(\s*"([a-z-]+)"', code)}
    used |= {f"category.{c.value}" for c in Category}
    used |= {f"state.{s.value}" for s in RefState}
    kinds = set(re.findall(r'kind="([a-z-]+)"', code))
    kinds |= set(re.findall(r'(?:add|ctx\.add)\([^()]*?,\s*"([a-z-]+)"', code))
    assert {"bind", "volume-device", "raw-text", "project-dir"} <= kinds
    used |= {f"kind.{k}" for k in kinds}
    assert len(used) > 25
    missing = sorted(k for k in used if k not in EN)
    assert missing == []


def test_frontend_keys_exist() -> None:
    js = (SRC / "web" / "static" / "app.js").read_text()
    html = (SRC / "web" / "index.html").read_text()
    keys = set(re.findall(r"\bt\('([a-zA-Z.-]*[a-zA-Z-])'", js))
    keys |= set(re.findall(r'data-i18n(?:-label)?="([a-zA-Z.-]+)"', html))
    assert len(keys) > 20
    for key in keys:
        assert key in EN or f"{key}_other" in EN, key


def test_translate_and_plurals() -> None:
    assert i18n.translate("row.orphanedFor", "de", count=1) == "seit 1 Tag verwaist"
    assert i18n.translate("row.orphanedFor", "de", count=3) == "seit 3 Tagen verwaist"
    assert i18n.translate("category.orphan", "xx") == "Orphaned"  # unknown language -> English
    assert i18n.translate("no.such.key") == "no.such.key"
    assert i18n.resolve_language("de-AT") == "de"
    assert i18n.resolve_language("fr") == "en"
    assert i18n.available_languages()[0]["code"] == "en"


def test_glossary_terms() -> None:
    """The key terms are used the same way everywhere (see docs/glossary.md)."""
    de = json.loads((i18n.LOCALES_DIR / "de.json").read_text())
    assert EN["category.orphan"] == "Orphaned" and de["category.orphan"] == "Verwaist"
    for text in EN.values():
        assert not re.search(r"\b(unused|dangling|dead)\b", text, re.I), text
    for text in de.values():
        assert not re.search(r"\b(unbenutzt|benutzt|Leiche)", text), text
