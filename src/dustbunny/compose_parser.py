"""Extract host paths from compose files.

The parser is deliberately generous: every host path a compose file mentions
becomes a :class:`~dustbunny.models.Reference`. Missing a reference can make a
live folder look orphaned, an extra reference only hides an orphan.

Covered:

* ``services.*.volumes`` in short (``src:dst[:opts]``) and long syntax
* top-level ``volumes.*.driver_opts.device`` (named volume bound to a path)
* ``env_file``, ``build`` context, ``extends.file``, top-level ``include``,
  ``configs.*.file`` and ``secrets.*.file``
* a regex over the raw text for absolute paths as a safety net (this also
  catches commented-out lines, which is intended)
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dustbunny.i18n import warning
from dustbunny.interpolation import interpolate, parse_dotenv, uses_defaults
from dustbunny.models import Notice, Reference, RefState
from dustbunny.paths import (
    MARK_END,
    MARK_START,
    display,
    has_unresolved,
    mark_unresolved,
    normalize,
    normalize_glob,
    split_outside_markers,
    to_glob,
)

COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)

# Absolute paths in free text. A path must not be glued to a preceding word,
# variable or marker (so "${DATA}/sonarr" doesn't yield a bogus "/sonarr").
_RAW_PATH_RE = re.compile(
    rf"(?<![\w.~/$\-{MARK_START}{MARK_END}])"
    rf"/(?!/)[^\s'\"`,;:|<>(){{}}\[\]=*?{MARK_START}{MARK_END}]+"
)


@dataclass
class ParseResult:
    references: list[Reference] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)
    project: str | None = None


class _LenientLoader(yaml.SafeLoader):
    """SafeLoader that tolerates compose's custom tags (``!reset``, ``!override``)."""


def _construct_unknown(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_LenientLoader.add_multi_constructor("!", _construct_unknown)


def parse_compose(
    text: str,
    *,
    env: Mapping[str, str] | None = None,
    base_dir: str | None = None,
    source: str = "compose",
    owner: str | None = None,
    origin: str | None = None,
    state: RefState = RefState.DEFINED,
    warn_relative: bool = True,
) -> ParseResult:
    """Parse compose ``text`` and return every host path it references.

    ``base_dir`` is the host directory relative paths are resolved against.
    Without it, relative paths are skipped - with a warning, unless
    ``warn_relative`` is off because they can't matter (Portainer: they point
    into Portainer's own data folder, never into a scan root).
    """
    env = env or {}
    ctx = _Context(
        base_dir=normalize(base_dir) if base_dir else None,
        source=source,
        owner=owner,
        origin=origin,
        state=state,
        warn_relative=warn_relative,
    )

    try:
        document = yaml.load(text, Loader=_LenientLoader)  # SafeLoader subclass
    except yaml.YAMLError as exc:
        ctx.warn("compose-invalid-yaml", error=str(exc).splitlines()[0])
        document = None

    if document is not None and not isinstance(document, dict):
        ctx.warn("compose-not-mapping")
        document = None

    if document is not None:
        resolved = _interpolate_tree(document, env, defaults=True)
        if isinstance(resolved.get("name"), str) and not has_unresolved(resolved["name"]):
            ctx.project = resolved["name"]
            ctx.owner = ctx.owner or resolved["name"]
        _extract_structured(resolved, ctx)
        if uses_defaults(text):
            # A variable with a default may still be set where we can't see it
            # (shell, Portainer globals): also keep what it would be as unknown.
            # Only references count from this pass, its warnings would be noise.
            warnings = list(ctx.warnings)
            ctx.alternative = True
            _extract_structured(_interpolate_tree(document, env, defaults=False), ctx)
            ctx.alternative = False
            ctx.warnings = warnings

    _extract_raw(interpolate(text, env), ctx)
    return ParseResult(references=ctx.references, warnings=ctx.warnings, project=ctx.project)


def load_compose_file(
    path: str | Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    source: str = "compose",
    owner: str | None = None,
    state: RefState = RefState.DEFINED,
) -> ParseResult:
    """Read a compose file from disk, using a sibling ``.env`` for interpolation.

    The file's directory is used as the base for relative paths, so this is
    only correct when the file is visible under the same path as on the host.
    """
    path = Path(path)
    env: dict[str, str] = dict(extra_env or {})
    dotenv = path.parent / ".env"
    if dotenv.is_file():
        env = {**parse_dotenv(dotenv.read_text(encoding="utf-8", errors="replace"), env), **env}
    result = parse_compose(
        path.read_text(encoding="utf-8", errors="replace"),
        env=env,
        base_dir=str(path.parent.absolute()),
        source=source,
        owner=owner or path.parent.name,
        origin=str(path),
        state=state,
    )
    # The project directory itself counts: people often keep data next to the
    # compose file (e.g. /opt/appdata/foo/compose.yaml + ./config).
    result.references.append(
        Reference(
            path=normalize(str(path.parent.absolute())),
            source=source,
            kind="project-dir",
            state=state,
            owner=owner or result.project or path.parent.name,
            origin=str(path),
        )
    )
    return result


def find_compose_files(directory: str | Path) -> list[Path]:
    """Compose files directly in ``directory`` incl. ``*.override.y(a)ml`` variants."""
    directory = Path(directory)
    found: list[Path] = []
    for name in COMPOSE_FILENAMES:
        stem, ext = name.rsplit(".", 1)
        for candidate in (directory / name, directory / f"{stem}.override.{ext}"):
            if candidate.is_file() and candidate not in found:
                found.append(candidate)
    return found


# --------------------------------------------------------------------------- internals


@dataclass
class _Context:
    base_dir: str | None
    source: str
    owner: str | None
    origin: str | None
    state: RefState
    project: str | None = None
    warn_relative: bool = True
    alternative: bool = False  # adding references of the "variable set elsewhere" pass
    references: list[Reference] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)
    _seen: set[tuple[str, str]] = field(default_factory=set)

    def warn(self, code: str, **params: str) -> None:
        item = warning(code, file=self.origin or self.owner or "compose", **params)
        if item not in self.warnings:
            self.warnings.append(item)

    def add(self, raw_path: str, kind: str, detail: str | None = None) -> None:
        resolved = self._resolve(raw_path, detail or kind)
        if resolved is None:
            return
        glob = normalize_glob(to_glob(resolved)) if has_unresolved(resolved) else None
        shown = display(resolved) if glob else normalize(resolved)
        key = (glob or shown, kind)
        if key in self._seen:
            return
        self._seen.add(key)
        self.references.append(
            Reference(
                path=shown,
                source=self.source,
                kind=kind,
                state=self.state,
                owner=self.owner,
                origin=_join_origin(self.origin, detail),
                glob=glob,
                alternative=self.alternative,
            )
        )

    def _resolve(self, value: str, what: str) -> str | None:
        value = value.strip()
        if not value:
            return None
        if value == "~" or value.startswith("~/"):
            # The host user's home directory is unknown to us.
            value = mark_unresolved("~") + value[1:]
        if value.startswith(("/", MARK_START)):
            return value
        if self.base_dir is None:
            if self.warn_relative:
                self.warn("compose-relative-path", path=display(value), detail=what)
            return None
        return posixpath.join(self.base_dir, value)


def _join_origin(origin: str | None, detail: str | None) -> str | None:
    if origin and detail:
        return f"{origin} ({detail})"
    return origin or detail


def _interpolate_tree(node: Any, env: Mapping[str, str], *, defaults: bool) -> Any:
    if isinstance(node, dict):
        return {key: _interpolate_tree(v, env, defaults=defaults) for key, v in node.items()}
    if isinstance(node, list):
        return [_interpolate_tree(item, env, defaults=defaults) for item in node]
    if isinstance(node, str):
        return interpolate(node, env, defaults=defaults)
    return node


def _looks_like_host_path(value: str) -> bool:
    """Short-syntax volume source: path (bind) or volume name?"""
    if value.startswith(("/", ".", "~")):
        return True
    # Volume names can't contain "/"; an unresolved prefix followed by a
    # path ("${DATA}/x") is a path, a lone "${VOL}" is ambiguous.
    return "/" in _strip_markers(value)


def _strip_markers(value: str) -> str:
    return re.sub(f"{MARK_START}[^{MARK_END}]*{MARK_END}", "", value)


def _is_remote(value: str) -> bool:
    return "://" in value or value.startswith(("git@", "github.com/"))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _extract_structured(doc: dict[str, Any], ctx: _Context) -> None:
    volumes = doc.get("volumes")
    if isinstance(volumes, dict):
        for name, cfg in volumes.items():
            if not isinstance(cfg, dict):
                continue
            device = (cfg.get("driver_opts") or {}).get("device")
            if isinstance(device, str) and (device.startswith(("/", ".", "~", MARK_START))):
                ctx.add(device, "volume-device", f"volume {name}")

    for section in ("configs", "secrets"):
        entries = doc.get(section)
        if isinstance(entries, dict):
            for name, cfg in entries.items():
                if isinstance(cfg, dict) and isinstance(cfg.get("file"), str):
                    ctx.add(cfg["file"], section[:-1], f"{section[:-1]} {name}")

    for item in _as_list(doc.get("include")):
        if isinstance(item, str):
            ctx.add(item, "include")
        elif isinstance(item, dict):
            for path in _as_list(item.get("path")):
                if isinstance(path, str):
                    ctx.add(path, "include")
            for path in _as_list(item.get("env_file")):
                if isinstance(path, str):
                    ctx.add(path, "env-file", "include")
            if isinstance(item.get("project_directory"), str):
                ctx.add(item["project_directory"], "include")

    services = doc.get("services")
    if isinstance(services, dict):
        for service_name, service in services.items():
            if isinstance(service, dict):
                _extract_service(str(service_name), service, ctx)


def _extract_service(name: str, service: dict[str, Any], ctx: _Context) -> None:
    detail = f"service {name}"
    for volume in _as_list(service.get("volumes")):
        if isinstance(volume, str):
            parts = split_outside_markers(volume, ":")
            if len(parts) < 2:
                continue  # anonymous volume, container path only
            src = parts[0]
            if _looks_like_host_path(src):
                ctx.add(src, "bind", detail)
            elif has_unresolved(src) and not _strip_markers(src):
                ctx.warn("compose-unresolved-volume", detail=detail, path=display(src))
        elif isinstance(volume, dict):
            src = volume.get("source")
            if volume.get("type") == "bind" and isinstance(src, str):
                ctx.add(src, "bind", detail)

    for env_file in _as_list(service.get("env_file")):
        path = env_file.get("path") if isinstance(env_file, dict) else env_file
        if isinstance(path, str):
            ctx.add(path, "env-file", detail)

    build = service.get("build")
    context = build.get("context") if isinstance(build, dict) else build
    if isinstance(context, str) and not _is_remote(context):
        ctx.add(context, "build-context", detail)

    extends = service.get("extends")
    if isinstance(extends, dict) and isinstance(extends.get("file"), str):
        ctx.add(extends["file"], "extends", detail)


def _extract_raw(text: str, ctx: _Context) -> None:
    structured = {r.path for r in ctx.references} | {r.glob for r in ctx.references if r.glob}
    for match in _RAW_PATH_RE.finditer(text):
        path = normalize(match.group(0).rstrip("."))
        if path == "/" or path in structured:
            continue
        ctx.add(path, "raw-text", "found in file text")
