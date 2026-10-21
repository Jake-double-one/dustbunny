"""Filesystem side: list candidate folders and gather size/age statistics."""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dustbunny.models import Candidate
from dustbunny.paths import normalize


@dataclass
class DiscoveryResult:
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_roots(roots: Sequence[str]) -> list[str]:
    """Normalize scan roots and reject unsafe values."""
    result: list[str] = []
    for raw in roots:
        raw = raw.strip()
        if not raw:
            continue
        if not raw.startswith("/"):
            raise ValueError(f"scan root {raw!r} must be an absolute path")
        root = normalize(raw)
        if root == "/":
            raise ValueError("scanning '/' is not supported, use a dedicated appdata folder")
        if root not in result:
            result.append(root)
    if not result:
        raise ValueError("no scan roots configured (SCAN_ROOTS)")
    return result


def discover(roots: Sequence[str], *, with_stats: bool = True) -> DiscoveryResult:
    """Return every direct subfolder of every root as a candidate."""
    result = DiscoveryResult()
    for root in roots:
        try:
            root_stat = os.stat(root)
        except OSError as exc:
            result.warnings.append(f"scan root {root} is not accessible: {exc.strerror}")
            continue
        if not stat.S_ISDIR(root_stat.st_mode):
            result.warnings.append(f"scan root {root} is not a directory")
            continue
        real_root = os.path.realpath(root)
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError as exc:
            result.warnings.append(f"scan root {root} cannot be listed: {exc.strerror}")
            continue
        for entry in entries:
            candidate = _candidate(entry, root, real_root, root_stat.st_dev, with_stats)
            if candidate is not None:
                result.candidates.append(candidate)
    return result


def _candidate(
    entry: os.DirEntry[str], root: str, real_root: str, root_dev: int, with_stats: bool
) -> Candidate | None:
    try:
        is_symlink = entry.is_symlink()
        if not is_symlink and not entry.is_dir(follow_symlinks=False):
            return None  # plain files in a root are not app folders
        entry_stat = entry.stat(follow_symlinks=False)
    except OSError:
        return None

    path = normalize(os.path.join(root, entry.name))
    real_path = normalize(os.path.join(real_root, entry.name))
    candidate = Candidate(
        path=path,
        root=root,
        name=entry.name,
        real_path=real_path if real_path != path else None,
        is_symlink=is_symlink,
        is_mountpoint=not is_symlink and entry_stat.st_dev != root_dev,
    )
    if is_symlink:
        candidate.last_modified = _ts(entry_stat.st_mtime)
        return candidate
    if with_stats:
        size, mtime, complete = tree_stats(path)
        candidate.size_bytes = size
        candidate.last_modified = _ts(mtime)
        candidate.stats_complete = complete
    return candidate


def tree_stats(path: str) -> tuple[int, float, bool]:
    """Disk usage (like ``du``), newest mtime and completeness of a directory tree.

    Does not follow symlinks, does not cross into other filesystems and counts
    hard-linked files once.
    """
    top = os.lstat(path)
    device = top.st_dev
    total = _usage(top)
    newest = top.st_mtime
    complete = True
    seen_inodes: set[int] = set()
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError:
            complete = False
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                complete = False
                continue
            newest = max(newest, st.st_mtime)
            if st.st_dev != device:
                continue  # separate mount below the folder: don't count it
            if st.st_nlink > 1 and not stat.S_ISDIR(st.st_mode):
                if st.st_ino in seen_inodes:
                    continue
                seen_inodes.add(st.st_ino)
            total += _usage(st)
            if stat.S_ISDIR(st.st_mode):
                stack.append(entry.path)
    return total, newest, complete


def _usage(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def _ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)
