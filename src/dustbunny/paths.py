"""Pure path helpers. Nothing in here touches the filesystem.

All paths handled by Dustbunny are POSIX host paths. They are normalized
lexically (``//a/./b/../c/`` -> ``/a/c``) but never resolved through symlinks
here, because the paths reported by Docker refer to the host, not to the
filesystem the code is running on.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Mapping

# Unresolvable parts of a path (unknown ``${VAR}``, ``~``) are carried around
# wrapped in these two control characters so that the original text survives
# for display while the matcher can treat them as wildcards.
MARK_START = "\x00"
MARK_END = "\x01"
_MARKER_RE = re.compile(f"{MARK_START}[^{MARK_END}]*{MARK_END}")


def mark_unresolved(text: str) -> str:
    return f"{MARK_START}{text}{MARK_END}"


def has_unresolved(value: str) -> bool:
    return MARK_START in value


def display(value: str) -> str:
    """Strip markers, keeping the original (unresolved) text."""
    return value.replace(MARK_START, "").replace(MARK_END, "")


def to_glob(value: str) -> str:
    """Replace every unresolved part with ``*``."""
    return _MARKER_RE.sub("*", value)


def split_outside_markers(value: str, sep: str) -> list[str]:
    """``str.split`` that ignores separators inside unresolved markers."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in value:
        if char == MARK_START:
            depth += 1
        elif char == MARK_END:
            depth = max(0, depth - 1)
        if char == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def normalize(path: str) -> str:
    """Lexically normalize an absolute POSIX path."""
    norm = posixpath.normpath(path)
    # POSIX allows a leading "//" to mean something special; Docker doesn't.
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    return norm


def is_under(child: str, parent: str) -> bool:
    """True if ``child`` lies strictly below ``parent`` (both normalized)."""
    if parent == "/":
        return child != "/" and child.startswith("/")
    return child.startswith(parent + "/")


def is_same_or_under(child: str, parent: str) -> bool:
    return child == parent or is_under(child, parent)


def parse_aliases(items: Iterable[str]) -> dict[str, str]:
    """Parse ``HOST_PREFIX=LOCAL_PREFIX`` pairs."""
    aliases: dict[str, str] = {}
    for item in items:
        item = item.strip()
        if not item:
            continue
        host, sep, local = item.partition("=")
        if not sep or not host.strip() or not local.strip():
            raise ValueError(f"invalid path alias {item!r}, expected HOST_PATH=LOCAL_PATH")
        host, local = normalize(host.strip()), normalize(local.strip())
        if not host.startswith("/") or not local.startswith("/"):
            raise ValueError(f"path alias {item!r} must use absolute paths")
        aliases[host] = local
    return aliases


def apply_aliases(path: str, aliases: Mapping[str, str]) -> str:
    """Translate a host path to the local view using the longest matching prefix."""
    best = ""
    for host in aliases:
        if is_same_or_under(path, host) and len(host) > len(best):
            best = host
    if not best:
        return path
    rest = path if best == "/" else path[len(best) :]
    return normalize(aliases[best] + rest) if rest else aliases[best]
