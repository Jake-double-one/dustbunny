"""Skins: one CSS file per skin - the built-in ones in ``skins/`` and your own
in ``SKINS_DIR`` (default ``<DATA_DIR>/skins``). They are read at runtime and
again a few seconds after a change, so a new file shows up without a rebuild.
See ``skins/README.md`` for the format.

Same format and tokens as in ShopWiz, so a skin works in both apps.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "skins"

# The colours every skin has; a missing one comes from the standard skin of the same kind.
TOKENS = (
    "bg", "surface", "surface-2", "ink", "muted", "line", "dusk", "dusk-soft", "sun",
    "sun-soft", "alert", "ok", "control", "control-ink", "on-dusk", "on-sun", "on-alert",
    "focus-bg", "focus-ink", "focus-dim", "shadow",
)  # fmt: skip
_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$", re.IGNORECASE)
# anything that could leave the CSS block (;{}<>) or load something (url, @, \) is refused
_SAFE_VALUE_RE = re.compile(r"^[#a-z0-9(),.%\s+-]{1,200}$", re.IGNORECASE)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
_META_RE = re.compile(r"^\s*\*?\s*([a-z]+(?:\.[a-z-]+)?)\s*:\s*(.+?)\s*$", re.IGNORECASE)
_VAR_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;{}]*?)\s*(?:;|(?=}))", re.IGNORECASE)
MAX_FILE_SIZE = 20_000


@dataclass
class Skin:
    id: str
    names: dict[str, str]
    scheme: str
    default: str | None
    order: float
    vars: dict[str, str]
    problems: list[str] = field(default_factory=list)


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two #rrggbb colours."""

    def lum(hex_color: str) -> float:
        channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, bl = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


_TEXT_PAIRS = (
    ("ink", "bg"), ("ink", "surface"), ("ink", "surface-2"), ("ink", "dusk-soft"),
    ("ink", "sun-soft"), ("muted", "bg"), ("muted", "surface"), ("dusk", "surface"),
    ("dusk", "bg"), ("alert", "surface"), ("ok", "surface"), ("surface", "ok"),
    ("on-dusk", "dusk"), ("on-sun", "sun"), ("on-alert", "alert"), ("focus-ink", "focus-bg"),
)  # fmt: skip


def contrast_problems(values: dict[str, str]) -> list[str]:
    """Text on its backgrounds needs 4.5:1, control borders 3:1 (WCAG AA)."""
    out = []

    def check(a: str, b: str, minimum: float) -> None:
        if not _COLOR_RE.match(values.get(a, "")) or not _COLOR_RE.match(values.get(b, "")):
            return
        ratio = contrast(values[a], values[b])
        if ratio < minimum:
            out.append(f"{a} on {b} {ratio:.2f}:1 (needs {minimum:g}:1)")

    for a, b in _TEXT_PAIRS:
        check(a, b, 4.5)
    check("control", "surface", 3)
    return out


def parse_skin(skin_id: str, text: str) -> Skin:
    problems: list[str] = []
    head_match = re.match(r"^\s*/\*([\s\S]*?)\*/", text)
    meta: dict[str, str] = {}
    for line in (head_match.group(1) if head_match else "").split("\n"):
        # "name: Ocean   <- explanation": everything from an arrow on is a comment
        match = _META_RE.match(re.sub(r"\s*←.*$", "", line))
        if match:
            meta[match.group(1).lower()] = match.group(2)
    names = {"": meta.get("name") or skin_id}
    names.update({k[5:]: v for k, v in meta.items() if k.startswith("name.")})
    scheme = "dark" if meta.get("scheme") == "dark" else "light"
    if meta.get("scheme") and meta["scheme"] not in ("dark", "light"):
        problems.append(f'scheme must be light or dark, not "{meta["scheme"]}"')
    values: dict[str, str] = {}
    body = re.sub(r"/\*[\s\S]*?\*/", "", text)
    for match in _VAR_RE.finditer(body):
        name, value = match.group(1).lower(), match.group(2)
        if name not in TOKENS:
            problems.append(f"unknown colour --{name}")
        elif not _SAFE_VALUE_RE.match(value) or (name != "shadow" and not _COLOR_RE.match(value)):
            expected = "a valid shadow" if name == "shadow" else "a #rrggbb colour"
            problems.append(f'--{name}: "{value[:40]}" is not {expected}')
        else:
            values[name] = value.lower()
    try:
        order = float(meta.get("order", "100"))
    except ValueError:
        order = 100.0
    default = meta.get("default")
    return Skin(
        id=skin_id,
        names=names,
        scheme=scheme,
        default=default if default in ("dark", "light") else None,
        order=order,
        vars=values,
        problems=problems,
    )


def _read_dir(directory: Path | None) -> list[Skin]:
    if directory is None or not directory.is_dir():
        return []
    skins = []
    for path in sorted(directory.glob("*.css")):
        skin_id = path.stem.lower()
        if not _ID_RE.match(skin_id):
            log.warning(
                'skin "%s" skipped: the file name may only have a-z, 0-9 and "-"', path.name
            )
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                raise ValueError("larger than 20 kB")
            skins.append(parse_skin(skin_id, path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            log.warning('skin "%s" skipped: %s', path.name, exc)
    return skins


def _block(selectors: list[str], skin: Skin, indent: str = "") -> str:
    lines = [f"{indent}  --{t}: {skin.vars[t]};" for t in TOKENS if t in skin.vars]
    lines.append(f"{indent}  color-scheme: {skin.scheme};")
    return (
        f"{indent}{(',' + chr(10) + indent).join(selectors)} {{\n"
        + "\n".join(lines)
        + f"\n{indent}}}"
    )


@dataclass
class SkinSet:
    skins: list[Skin]
    css: str
    defaults: dict[str, str]

    def as_list(self) -> dict[str, object]:
        return {
            "defaults": self.defaults,
            "skins": [
                {
                    "id": s.id,
                    "names": s.names,
                    "scheme": s.scheme,
                    "bg": s.vars.get("bg"),
                    "accent": s.vars.get("dusk"),
                }
                for s in self.skins
            ],
        }

    def html(self) -> str:
        """``<style>`` + JSON list for the page; ``<`` escaped so nothing can end the tag."""
        data = json.dumps(self.as_list()).replace("<", "\\u003c")
        return (
            f'<style id="skins">\n{self.css}\n</style>\n'
            f'<script type="application/json" id="skin-list">{data}</script>'
        )


def load_skins(builtin_dir: Path = BUILTIN_DIR, custom_dir: Path | None = None) -> SkinSet:
    """All skins (built-in, then your own - the same name replaces a built-in one)."""
    by_id = {s.id: s for s in [*_read_dir(builtin_dir), *_read_dir(custom_dir)]}
    skins = sorted(by_id.values(), key=lambda s: (s.order, s.id))
    if not skins:
        raise FileNotFoundError(f"no skins found in {builtin_dir}")
    standard: dict[str, Skin] = {}
    for scheme in ("light", "dark"):
        standard[scheme] = (
            next((s for s in skins if s.default == scheme), None)
            or next((s for s in skins if s.scheme == scheme), None)
            or skins[0]
        )
    for skin in skins:
        base = standard[skin.scheme]
        missing = [t for t in TOKENS if t not in skin.vars and t in base.vars]
        if missing and skin is not base:
            listed = ", ".join(f"--{t}" for t in missing)
            skin.problems.append(f'missing {listed} - taken from "{base.id}"')
        skin.vars = {**base.vars, **skin.vars}
        skin.problems.extend(f"low contrast: {p}" for p in contrast_problems(skin.vars))
        for problem in skin.problems:
            log.warning('skin "%s": %s', skin.id, problem)
    skins = [s for s in skins if all(t in s.vars or t == "shadow" for t in TOKENS)]
    light, dark = standard["light"], standard["dark"]
    css = "\n".join(
        [
            "/* skins - put together by the server from skins/ and SKINS_DIR */",
            _block([":root", f":root[data-theme='{light.id}']"], light),
            _block([f":root[data-theme='{dark.id}']"], dark),
            "@media (prefers-color-scheme: dark) {\n"
            + _block([":root[data-theme='auto']"], dark, "  ")
            + "\n}",
            *(
                _block([f":root[data-theme='{s.id}']"], s)
                for s in skins
                if s is not light and s is not dark
            ),
        ]
    )
    return SkinSet(skins=skins, css=css, defaults={"light": light.id, "dark": dark.id})


class SkinCache:
    """Re-reads the skin folders when a file changes (checked every few seconds)."""

    def __init__(
        self, builtin_dir: Path = BUILTIN_DIR, custom_dir: Path | None = None, check_s: float = 5
    ):
        self.builtin_dir, self.custom_dir, self.check_s = builtin_dir, custom_dir, check_s
        self._lock = threading.Lock()
        self._cache: SkinSet | None = None
        self._signature = ""
        self._checked = 0.0

    def _current_signature(self) -> str:
        parts = []
        for directory in (self.builtin_dir, self.custom_dir):
            if directory is not None and directory.is_dir():
                for path in sorted(directory.glob("*.css")):
                    st = path.stat()
                    parts.append(f"{path}:{st.st_size}:{st.st_mtime_ns}")
        return "|".join(parts)

    def get(self) -> SkinSet:
        with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._checked < self.check_s:
                return self._cache
            self._checked = now
            signature = self._current_signature()
            if self._cache is not None and signature == self._signature:
                return self._cache
            try:
                self._cache = load_skins(self.builtin_dir, self.custom_dir)
                self._signature = signature
            except (OSError, ValueError) as exc:
                log.error("skins could not be read: %s", exc)
                if self._cache is None:
                    raise
            return self._cache
