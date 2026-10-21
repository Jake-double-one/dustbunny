"""Translations shared by the server, the CLI and the web UI.

Every language is one JSON file in ``locales/`` named after its code
(``en.json``, ``de.json``, ...). English is the primary language and the
fallback for missing keys. A new file is picked up without code changes;
``tests/test_locales.py`` checks that it has the same keys as ``en.json``.

Keys are flat (``"reason.no-reference"``). ``{name}`` is a placeholder. A key
used with a ``count`` parameter may have ``_one``/``_other`` variants.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from dustbunny.models import Notice

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "en"
_CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@cache
def load_locale(code: str) -> dict[str, str]:
    if not _CODE_RE.fullmatch(code):
        raise KeyError(code)
    path = LOCALES_DIR / f"{code}.json"
    if not path.is_file():
        raise KeyError(code)
    return json.loads(path.read_text(encoding="utf-8"))


def available_languages() -> list[dict[str, str]]:
    """``[{"code": "en", "name": "English"}, ...]`` - English first, then by code."""
    codes = sorted(p.stem for p in LOCALES_DIR.glob("*.json") if _CODE_RE.fullmatch(p.stem))
    codes.sort(key=lambda c: c != DEFAULT_LANGUAGE)
    return [{"code": c, "name": load_locale(c).get("language.name", c)} for c in codes]


def resolve_language(code: str | None) -> str:
    """Best available language for ``code`` (``de-AT`` -> ``de``), else English."""
    known = {lang["code"] for lang in available_languages()}
    if code:
        code = code.strip().lower()
        for candidate in (code, code.split("-")[0]):
            if candidate in known:
                return candidate
    return DEFAULT_LANGUAGE


def translate(key: str, lang: str = DEFAULT_LANGUAGE, **params: Any) -> str:
    try:
        table = load_locale(lang)
    except KeyError:
        table = {}
    fallback = load_locale(DEFAULT_LANGUAGE)
    keys = [key]
    if isinstance(params.get("count"), int):
        keys.insert(0, f"{key}_{'one' if params['count'] == 1 else 'other'}")
    text = next((t[k] for k in keys for t in (table, fallback) if k in t), key)
    return _PLACEHOLDER_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)


def notice(prefix: str, code: str, **params: Any) -> Notice:
    """A :class:`Notice` with its English message from ``<prefix>.<code>``."""
    return Notice(
        code=code,
        message=translate(f"{prefix}.{code}", **params),
        params={k: str(v) for k, v in params.items()},
    )


def reason(code: str, **params: Any) -> Notice:
    return notice("reason", code, **params)


def warning(code: str, **params: Any) -> Notice:
    return notice("warning", code, **params)
