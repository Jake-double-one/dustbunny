"""Compose-style variable interpolation and ``.env`` parsing.

Implements the compose-spec rules: ``$$``, ``$VAR``, ``${VAR}``,
``${VAR:-default}``, ``${VAR-default}``, ``${VAR:?err}``, ``${VAR?err}``,
``${VAR:+alt}``, ``${VAR+alt}``, including nested expressions in defaults.

Unlike docker compose, an unknown variable is *not* replaced with an empty
string: we usually don't see the full environment (shell env, Portainer
globals, ``.env`` in a git repo), so the expression is kept as an
"unresolved" marker (see :mod:`dustbunny.paths`) and later treated as a
wildcard. That way ``${DATA}/sonarr`` still protects ``/opt/appdata/sonarr``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from dustbunny.paths import mark_unresolved

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPERATORS = (":-", ":?", ":+", "-", "?", "+")


def interpolate(text: str, env: Mapping[str, str]) -> str:
    """Substitute variables in ``text``; unknown ones become unresolved markers."""
    result, _ = _interpolate(text, 0, env, stop_at_brace=False)
    return result


def _interpolate(text: str, pos: int, env: Mapping[str, str], *, stop_at_brace: bool):
    out: list[str] = []
    length = len(text)
    while pos < length:
        char = text[pos]
        if stop_at_brace and char == "}":
            return "".join(out), pos
        if char != "$":
            out.append(char)
            pos += 1
            continue
        nxt = text[pos + 1] if pos + 1 < length else ""
        if nxt == "$":
            out.append("$")
            pos += 2
        elif nxt == "{":
            value, pos = _braced(text, pos, env)
            out.append(value)
        else:
            match = _NAME_RE.match(text, pos + 1)
            if match is None:
                out.append("$")
                pos += 1
                continue
            name = match.group(0)
            out.append(env[name] if name in env else mark_unresolved("$" + name))
            pos = match.end()
    return "".join(out), pos


def _braced(text: str, start: int, env: Mapping[str, str]) -> tuple[str, int]:
    """Handle ``${...}`` starting at ``text[start] == '$'``. Returns (value, new_pos)."""
    match = _NAME_RE.match(text, start + 2)
    if match is None:
        # Not a valid expression: keep it literally (compose would error out).
        end = text.find("}", start)
        end = len(text) if end == -1 else end + 1
        return text[start:end], end
    name = match.group(0)
    pos = match.end()
    operator = next((op for op in _OPERATORS if text.startswith(op, pos)), None)
    word = ""
    if operator is not None:
        word, pos = _interpolate(text, pos + len(operator), env, stop_at_brace=True)
    if pos >= len(text) or text[pos] != "}":
        # Unterminated: keep the rest literally.
        return text[start:], len(text)
    end = pos + 1
    original = text[start:end]

    is_set = name in env
    value = env.get(name, "")
    match operator:
        case None:
            return (value if is_set else mark_unresolved(original)), end
        case ":-":
            return (value if is_set and value else word), end
        case "-":
            return (value if is_set else word), end
        case ":?":
            return (value if is_set and value else mark_unresolved(original)), end
        case "?":
            return (value if is_set else mark_unresolved(original)), end
        case ":+":
            return (word if is_set and value else ""), end
        case "+":
            return (word if is_set else ""), end
    raise AssertionError(operator)  # pragma: no cover


def parse_dotenv(text: str, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Parse a compose ``.env`` file.

    Values may reference earlier variables (and ``base_env``) like compose
    allows. Single-quoted values are taken literally.
    """
    env: dict[str, str] = {}
    lookup = _ChainEnv(env, base_env or {})
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _NAME_RE.fullmatch(key):
            continue
        value = value.strip()
        if value[:1] == "'":
            end = value.find("'", 1)
            env[key] = value[1:end] if end != -1 else value[1:]
        elif value[:1] == '"':
            env[key] = interpolate(_double_quoted(value), lookup)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            env[key] = interpolate(value, lookup)
    return env


def _double_quoted(value: str) -> str:
    out: list[str] = []
    pos = 1
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "$": "$$"}
    while pos < len(value):
        char = value[pos]
        if char == "\\" and pos + 1 < len(value):
            out.append(escapes.get(value[pos + 1], "\\" + value[pos + 1]))
            pos += 2
            continue
        if char == '"':
            break
        out.append(char)
        pos += 1
    return "".join(out)


class _ChainEnv(Mapping[str, str]):
    def __init__(self, first: Mapping[str, str], second: Mapping[str, str]):
        self._first, self._second = first, second

    def __getitem__(self, key: str) -> str:
        if key in self._first:
            return self._first[key]
        return self._second[key]

    def __iter__(self):
        yield from self._first
        yield from (k for k in self._second if k not in self._first)

    def __len__(self) -> int:
        return len(set(self._first) | set(self._second))
