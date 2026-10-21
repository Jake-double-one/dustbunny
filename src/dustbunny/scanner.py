"""Filesystem side: list candidate folders and gather size/age statistics."""

from __future__ import annotations

import os
import stat
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NamedTuple

from dustbunny.birthtime import birth_time
from dustbunny.i18n import warning
from dustbunny.models import Candidate, Notice
from dustbunny.paths import apply_aliases, is_under, normalize


@dataclass
class DiscoveryResult:
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)
    failed_roots: list[str] = field(default_factory=list)


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


def discover(
    roots: Sequence[str], *, with_stats: bool = True, tracked: Collection[str] = ()
) -> DiscoveryResult:
    """Return every direct subfolder of every root as a candidate.

    ``tracked`` are referenced host paths (after PATH_ALIASES). The size of each
    one inside a folder is measured in the same walk as the folder itself.
    """
    result = DiscoveryResult()
    for root in roots:
        try:
            root_stat = os.stat(root)
        except OSError as exc:
            result.warnings.append(warning("root-missing", root=root, error=exc.strerror))
            result.failed_roots.append(root)
            continue
        if not stat.S_ISDIR(root_stat.st_mode):
            result.warnings.append(warning("root-not-directory", root=root))
            result.failed_roots.append(root)
            continue
        real_root = os.path.realpath(root)
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError as exc:
            result.warnings.append(warning("root-unreadable", root=root, error=exc.strerror))
            result.failed_roots.append(root)
            continue
        found = [_candidate(e, root, real_root, root_stat.st_dev) for e in entries]
        result.candidates.extend(c for c in found if c is not None)
        if not any(c is not None for c in found):
            # e.g. an NFS share or a disk array that isn't mounted (yet)
            result.warnings.append(warning("root-empty", root=root))

    if with_stats:
        # the matcher reads a mount of a symlinked folder as a mount of its target
        links = {c.path: c.link_target for c in result.candidates if c.link_target}
        tracked = {apply_aliases(path, links) for path in tracked}
        for candidate in result.candidates:
            if not candidate.is_symlink:
                _add_stats(candidate, tracked)
    return result


def _candidate(
    entry: os.DirEntry[str], root: str, real_root: str, root_dev: int
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
        created=birth_time(path),
    )
    if is_symlink:
        candidate.last_modified = _ts(entry_stat.st_mtime)
        target = normalize(os.path.realpath(path))
        candidate.link_target = target if target != path else None
    return candidate


def _add_stats(candidate: Candidate, tracked: Collection[str]) -> None:
    # tracked paths inside the folder, by where the walk finds them
    parts: dict[str, list[str]] = {}
    for base in filter(None, (candidate.path, candidate.real_path)):
        for path in tracked:
            if is_under(path, base):
                parts.setdefault(candidate.path + path[len(base) :], []).append(path)
    try:
        stats = tree_stats(candidate.path, parts)
    except OSError:  # removed while scanning
        candidate.stats_complete = False
        return
    candidate.size_bytes = stats.size
    candidate.last_modified = _ts(stats.newest)
    candidate.stats_complete = stats.complete
    candidate.path_sizes = {
        path: size for found, size in stats.parts.items() for path in parts[found]
    }


# Hard-link heavy trees (rsnapshot) would make the inode set grow without limit;
# beyond this many, further hard links are counted every time they appear.
MAX_TRACKED_HARDLINKS = 1_000_000


class TreeStats(NamedTuple):
    size: int
    newest: float
    complete: bool
    parts: dict[str, int]  # size of each requested path below the top that exists


def tree_stats(path: str, parts: Collection[str] = ()) -> TreeStats:
    """Disk usage (like ``du``), newest mtime and completeness of a directory tree.

    Does not follow symlinks, does not cross into other filesystems and counts
    hard-linked files once. ``parts`` are paths below ``path`` (as the walk
    spells them) whose own size is wanted as well.
    """
    top = os.lstat(path)
    device = top.st_dev
    total = _usage(top)
    newest = top.st_mtime
    complete = True
    sizes: dict[str, int] = {}
    seen_inodes: set[int] = set()
    # each directory with the requested paths it lies in
    stack: list[tuple[str, tuple[str, ...]]] = [(path, ())]
    while stack:
        current, inside = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
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
                        if len(seen_inodes) < MAX_TRACKED_HARDLINKS:
                            seen_inodes.add(st.st_ino)
                    usage = _usage(st)
                    total += usage
                    owners = (*inside, entry.path) if entry.path in parts else inside
                    for owner in owners:
                        sizes[owner] = sizes.get(owner, 0) + usage
                    if stat.S_ISDIR(st.st_mode):
                        stack.append((entry.path, owners))
        except OSError:
            complete = False
    return TreeStats(total, newest, complete, sizes)


def _usage(st: os.stat_result) -> int:
    blocks = getattr(st, "st_blocks", None)
    return blocks * 512 if blocks is not None else st.st_size


def _ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)
