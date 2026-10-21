"""Decide for every candidate folder whether anything still references it.

Rules (see README "How detection works"):

* A reference R *protects* candidate D if R == D or R lies inside D.
* If D lies inside R, R covers a whole scan root (candidates are direct
  children of a root). Such broad mounts - backup tools, file managers -
  are listed for information but never protect a folder.
* References with unresolved parts (``${DATA}/sonarr``) protect D when a
  prefix of the pattern that ends in a literal path segment matches D.
* The best protecting reference decides the category:
  running > stopped > defined. Nothing protecting -> orphan.
* Symlinks, nested scan roots and ignore rules -> ignored (always wins).
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from dustbunny.i18n import reason, warning
from dustbunny.models import (
    Candidate,
    Category,
    FolderResult,
    Notice,
    Reference,
    ReferenceHit,
    RefState,
    Relation,
    ScanReport,
    SourceStatus,
    Summary,
)
from dustbunny.paths import apply_aliases, is_same_or_under, is_under, normalize, normalize_glob

# Folders that are never app data. Matched against the folder name.
BUILTIN_IGNORE = (
    "lost+found",
    ".quarantine",
    "@eaDir",
    "#recycle",
    "#snapshot",
    ".Trash-*",
)

CATEGORY_ORDER = (
    Category.ORPHAN,
    Category.DEFINED_ONLY,
    Category.STOPPED,
    Category.ACTIVE,
    Category.IGNORED,
)

# Warnings that mean "some references may be missing": such a report must not
# notify or change what Dustbunny remembers (see ScanReport.reliable).
UNCERTAIN_WARNINGS = frozenset(
    {
        "unresolved-path",
        "compose-invalid-yaml",
        "compose-not-mapping",
        "compose-unresolved-volume",
        "portainer-additional-files",
    }
)

_STATE_RANK = {RefState.RUNNING: 0, RefState.STOPPED: 1, RefState.DEFINED: 2}
_STATE_CATEGORY = {
    RefState.RUNNING: Category.ACTIVE,
    RefState.STOPPED: Category.STOPPED,
    RefState.DEFINED: Category.DEFINED_ONLY,
}
_STATE_REASON = {
    RefState.RUNNING: "used-running",
    RefState.STOPPED: "used-stopped",
    RefState.DEFINED: "defined-only",
}


@dataclass
class _PreparedRef:
    ref: Reference
    path: str | None = None  # normalized + aliased, for literal references
    prefixes: list[re.Pattern[str]] = field(default_factory=list)  # for pattern references
    full: re.Pattern[str] | None = None
    exact: re.Pattern[str] | None = None  # full pattern, if it ends in a literal segment


def _prepare(
    ref: Reference, aliases: Mapping[str, str], links: Mapping[str, str] | None = None
) -> _PreparedRef:
    """``aliases`` translate host paths (PATH_ALIASES), ``links`` map symlinks
    inside a scan root to their targets, so a mount of the link protects the target."""
    links = links or {}
    if ref.glob is None:
        path = apply_aliases(apply_aliases(normalize(ref.path), aliases), links)
        return _PreparedRef(ref=ref, path=path)
    glob = apply_aliases(apply_aliases(normalize_glob(ref.glob), aliases), links)
    segments = glob.split("/")
    prefixes = []
    for end in range(1, len(segments) + 1):
        last = segments[end - 1]
        if last and last.replace("*", ""):
            prefixes.append(_glob_regex("/".join(segments[:end])))
    full = _glob_regex(glob)
    exact = full if prefixes and prefixes[-1].pattern == full.pattern else None
    return _PreparedRef(ref=ref, prefixes=prefixes, full=full, exact=exact)


def _glob_regex(glob: str) -> re.Pattern[str]:
    # '*' stands for an unknown part and may span several path segments.
    return re.compile(".*".join(re.escape(part) for part in glob.split("*")))


def _relation(prepared: _PreparedRef, identity: str) -> Relation | None:
    if prepared.path is not None:
        if prepared.path == identity:
            return Relation.EXACT
        if is_under(prepared.path, identity):
            return Relation.INSIDE
        if is_under(identity, prepared.path):
            return Relation.BROAD
        return None
    if prepared.exact is not None and prepared.exact.fullmatch(identity):
        return Relation.EXACT
    if any(prefix.fullmatch(identity) for prefix in prepared.prefixes):
        return Relation.INSIDE
    return None


def _ignore_rule(candidate: Candidate, rules: Sequence[str]) -> str | None:
    relative = candidate.path[len(candidate.root) :].lstrip("/")
    for rule in rules:
        if "/" in rule:
            if fnmatch.fnmatchcase(candidate.path, rule) or fnmatch.fnmatchcase(relative, rule):
                return rule
        elif fnmatch.fnmatchcase(candidate.name, rule):
            return rule
    return None


def owners(hits: Iterable[ReferenceHit]) -> str:
    names: list[str] = []
    for hit in hits:
        name = hit.reference.owner or hit.reference.origin or hit.reference.path
        if name not in names:
            names.append(name)
    return ", ".join(names)


def classify(
    candidates: Iterable[Candidate],
    references: Iterable[Reference],
    *,
    roots: Sequence[str],
    ignore: Sequence[str] = (),
    ignored_paths: Collection[str] = (),
    aliases: Mapping[str, str] | None = None,
    checked_sources: Sequence[str] = (),
) -> list[FolderResult]:
    """``ignore`` are glob rules (IGNORE), ``ignored_paths`` exact folders
    ignored in the web UI."""
    aliases = aliases or {}
    candidates = list(candidates)
    roots = [normalize(r) for r in roots]
    links = symlink_aliases(candidates)
    prepared = [_prepare(ref, aliases, links) for ref in references]
    ignored = {normalize(p) for p in ignored_paths}
    return [_classify_one(c, prepared, roots, ignore, ignored, checked_sources) for c in candidates]


def symlink_aliases(candidates: Iterable[Candidate]) -> dict[str, str]:
    """``/opt/appdata/sonarr -> sonarr-v4``: a mount of the link uses the target."""
    return {
        normalize(c.path): normalize(c.link_target)
        for c in candidates
        if c.is_symlink and c.link_target
    }


def _classify_one(
    candidate: Candidate,
    prepared: Sequence[_PreparedRef],
    roots: Sequence[str],
    ignore: Sequence[str],
    ignored_paths: Collection[str],
    checked_sources: Sequence[str],
) -> FolderResult:
    identities = [normalize(candidate.path)]
    if candidate.real_path and normalize(candidate.real_path) not in identities:
        identities.append(normalize(candidate.real_path))

    protected: list[ReferenceHit] = []
    broad: list[ReferenceHit] = []
    for prep in prepared:
        for identity in identities:
            relation = _relation(prep, identity)
            if relation is None:
                continue
            hit = ReferenceHit(reference=prep.ref, relation=relation, matched_path=identity)
            (broad if relation is Relation.BROAD else protected).append(hit)
            break

    result = FolderResult(
        path=candidate.path,
        root=candidate.root,
        name=candidate.name,
        category=Category.ORPHAN,
        protected_by=protected,
        broad_access=broad,
        checked_sources=list(checked_sources),
        size_bytes=candidate.size_bytes,
        last_modified=candidate.last_modified,
        stats_complete=candidate.stats_complete,
        is_symlink=candidate.is_symlink,
        is_mountpoint=candidate.is_mountpoint,
    )

    ignored = _ignored_reason(candidate, identities, roots, ignore, ignored_paths)
    if ignored is not None:
        result.category = Category.IGNORED
        result.reasons.append(ignored)
    elif protected:
        best = min(protected, key=lambda h: _STATE_RANK[h.reference.state]).reference.state
        result.category = _STATE_CATEGORY[best]
        result.reasons.append(
            reason(
                _STATE_REASON[best],
                owners=owners(h for h in protected if h.reference.state is best),
            )
        )
        if any(h.reference.is_pattern for h in protected):
            result.reasons.append(reason("unresolved-match"))
    else:
        result.reasons.append(reason("no-reference"))
        if broad:
            result.reasons.append(reason("broad-access-only", owners=owners(broad)))

    if candidate.is_mountpoint:
        result.reasons.append(reason("mountpoint"))
    if not candidate.stats_complete:
        result.reasons.append(reason("stats-incomplete"))
    return result


def _ignored_reason(
    candidate: Candidate,
    identities: Sequence[str],
    roots: Sequence[str],
    ignore: Sequence[str],
    ignored_paths: Collection[str],
) -> Notice | None:
    if candidate.is_symlink:
        return reason("symlink", target=candidate.link_target or "?")
    for root in roots:
        if any(is_same_or_under(root, identity) for identity in identities):
            return reason("nested-root", root=root)
    rule = _ignore_rule(candidate, BUILTIN_IGNORE)
    if rule is not None:
        return reason("builtin-ignore", rule=rule)
    if normalize(candidate.path) in ignored_paths:
        return reason("ignored-by-user")
    rule = _ignore_rule(candidate, ignore)
    if rule is not None:
        return reason("ignore-rule", rule=rule)
    return None


def sanity_warnings(
    candidates: Sequence[Candidate],
    references: Sequence[Reference],
    roots: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> list[Notice]:
    """Detect setups that would make every folder look orphaned."""
    aliases = aliases or {}
    links = symlink_aliases(candidates)
    warnings: list[Notice] = []
    literal = [apply_aliases(normalize(r.path), aliases) for r in references if r.glob is None]
    for root in (normalize(r) for r in roots):
        in_root = [c for c in candidates if c.root == root]
        if not in_root:
            continue
        # a symlinked root is reported by Docker under its real path
        names = {root} | {c.real_path.rsplit("/", 1)[0] for c in in_root if c.real_path}
        if references and not any(is_under(path, r) for path in literal for r in names):
            warnings.append(warning("root-unreferenced", root=root))
    for ref in references:
        if ref.glob is None:
            continue
        prepared = _prepare(ref, aliases, links)
        if any(p.fullmatch(normalize(c.path)) for p in prepared.prefixes for c in candidates):
            continue
        glob = apply_aliases(normalize_glob(ref.glob), aliases)
        if "*" not in glob:
            continue
        # Could the unknown part stand for a folder in a scan root? An invisible
        # separator stands for "some folder" there.
        tail = glob.split("*", 1)[1]
        for root in (normalize(r) for r in roots):
            probe = f"{root}/\u2063{tail}"
            if prepared.full is not None and prepared.full.fullmatch(probe):
                warnings.append(
                    warning(
                        "unresolved-path",
                        owner=ref.owner or ref.origin or "?",
                        path=ref.path,
                        root=root,
                    )
                )
                break
    return warnings


def build_report(
    candidates: Sequence[Candidate],
    references: Sequence[Reference],
    *,
    roots: Sequence[str],
    sources: Sequence[SourceStatus],
    ignore: Sequence[str] = (),
    ignored_paths: Collection[str] = (),
    aliases: Mapping[str, str] | None = None,
    warnings: Sequence[Notice] = (),
    failed_roots: Sequence[str] = (),
) -> ScanReport:
    ok_sources = [s.name for s in sources if s.ok]
    folders = classify(
        candidates,
        references,
        roots=roots,
        ignore=ignore,
        ignored_paths=ignored_paths,
        aliases=aliases,
        checked_sources=ok_sources,
    )
    folders.sort(key=lambda f: (CATEGORY_ORDER.index(f.category), f.path))

    all_warnings = list(warnings)
    if not sources:
        all_warnings.append(warning("no-sources"))
    for status in sources:
        if not status.ok:
            all_warnings.append(
                warning("source-failed", source=status.name, error=status.error or "?")
            )
        all_warnings.extend(status.warnings)
    all_warnings.extend(sanity_warnings(candidates, references, roots, aliases))

    unique: dict[tuple[str, str], Notice] = {}
    for item in all_warnings:
        unique.setdefault((item.code, item.message), item)

    return ScanReport(
        roots=[normalize(r) for r in roots],
        complete=bool(sources) and all(s.ok for s in sources) and not failed_roots,
        uncertain=any(w.code in UNCERTAIN_WARNINGS for w in unique.values()),
        sources=list(sources),
        warnings=list(unique.values()),
        summary=summarize(folders),
        folders=folders,
    )


def summarize(folders: Iterable[FolderResult]) -> Summary:
    summary = Summary()
    for folder in folders:
        summary.total += 1
        summary.counts[folder.category] += 1
        size = folder.size_bytes or 0
        summary.total_bytes += size
        if folder.category is Category.ORPHAN:
            summary.orphan_bytes += size
    return summary
