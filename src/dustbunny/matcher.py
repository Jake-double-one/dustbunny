"""Decide for every candidate folder whether anything still references it.

Rules (see README "How detection works"):

* A reference R *protects* candidate D if R == D or R lies inside D.
* If D lies inside R, R covers a whole scan root (candidates are direct
  children of a root). Such "broad" mounts - backup tools, file managers -
  are listed for information but never protect a folder.
* References with unresolved parts (``${DATA}/sonarr``) protect D when a
  prefix of the pattern that ends in a literal path segment matches D.
* The best protecting reference decides the category:
  running > stopped > defined. Nothing protecting -> orphan.
* Ignore rules, symlinks and nested scan roots -> ignored (always wins).
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from dustbunny.models import (
    Candidate,
    Category,
    FolderResult,
    Reason,
    Reference,
    ReferenceHit,
    RefState,
    Relation,
    ScanReport,
    SourceStatus,
    Summary,
)
from dustbunny.paths import apply_aliases, is_same_or_under, is_under, normalize

# Folders that are never app data. Matched against the folder name.
BUILTIN_IGNORE = (
    "lost+found",
    ".quarantine",
    "@eaDir",
    "#recycle",
    "#snapshot",
    ".Trash-*",
)

_STATE_RANK = {RefState.RUNNING: 0, RefState.STOPPED: 1, RefState.DEFINED: 2}
_STATE_CATEGORY = {
    RefState.RUNNING: Category.ACTIVE,
    RefState.STOPPED: Category.STOPPED,
    RefState.DEFINED: Category.DEFINED_ONLY,
}


@dataclass
class _PreparedRef:
    ref: Reference
    path: str | None = None  # normalized + aliased, for literal references
    prefixes: list[re.Pattern[str]] = field(default_factory=list)  # for pattern references
    full: re.Pattern[str] | None = None
    exact: re.Pattern[str] | None = None  # full pattern, if it ends in a literal segment


def _prepare(ref: Reference, aliases: Mapping[str, str]) -> _PreparedRef:
    if ref.glob is None:
        return _PreparedRef(ref=ref, path=apply_aliases(normalize(ref.path), aliases))
    glob = apply_aliases(normalize(ref.glob), aliases)
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


def _ignore_rule(candidate: Candidate, ignore: Sequence[str]) -> str | None:
    relative = candidate.path[len(candidate.root) :].lstrip("/")
    for rule in ignore:
        target_is_path = "/" in rule
        if target_is_path:
            if fnmatch.fnmatchcase(candidate.path, rule) or fnmatch.fnmatchcase(relative, rule):
                return rule
        elif fnmatch.fnmatchcase(candidate.name, rule):
            return rule
    return None


def classify(
    candidates: Iterable[Candidate],
    references: Iterable[Reference],
    *,
    roots: Sequence[str],
    ignore: Sequence[str] = (),
    aliases: Mapping[str, str] | None = None,
    checked_sources: Sequence[str] = (),
) -> list[FolderResult]:
    aliases = aliases or {}
    roots = [normalize(r) for r in roots]
    prepared = [_prepare(ref, aliases) for ref in references]
    results = []
    for candidate in candidates:
        results.append(_classify_one(candidate, prepared, roots, ignore, checked_sources))
    return results


def _classify_one(
    candidate: Candidate,
    prepared: Sequence[_PreparedRef],
    roots: Sequence[str],
    ignore: Sequence[str],
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

    ignored = _ignored_reason(candidate, identities, roots, ignore)
    if ignored is not None:
        result.category = Category.IGNORED
        result.reasons.append(ignored)
    elif protected:
        best = min(protected, key=lambda h: _STATE_RANK[h.reference.state]).reference.state
        result.category = _STATE_CATEGORY[best]
        result.reasons.append(_protected_reason(best, protected))
        if any(h.reference.is_pattern for h in protected):
            result.reasons.append(
                Reason(
                    code="unresolved-match",
                    message="Matched a path with unresolved variables; "
                    "treated as referenced to be safe.",
                )
            )
    else:
        result.reasons.append(
            Reason(
                code="no-reference",
                message="Nothing references this folder or anything inside it.",
            )
        )
        if broad:
            owners = _owners(broad)
            result.reasons.append(
                Reason(
                    code="broad-access-only",
                    message=f"Only broad mounts of the whole root cover it ({owners}); "
                    "these don't count as usage.",
                )
            )

    if candidate.is_mountpoint:
        result.reasons.append(
            Reason(code="mountpoint", message="This folder is a separate mount point.")
        )
    if not candidate.stats_complete:
        result.reasons.append(
            Reason(
                code="stats-incomplete",
                message="Size/age are incomplete: some entries could not be read.",
            )
        )
    return result


def _ignored_reason(
    candidate: Candidate,
    identities: Sequence[str],
    roots: Sequence[str],
    ignore: Sequence[str],
) -> Reason | None:
    if candidate.is_symlink:
        return Reason(code="symlink", message="Symbolic link - never treated as app data.")
    for root in roots:
        if any(is_same_or_under(root, identity) for identity in identities):
            return Reason(code="nested-root", message=f"Is or contains the scan root {root}.")
    rule = _ignore_rule(candidate, BUILTIN_IGNORE)
    if rule is not None:
        return Reason(code="builtin-ignore", message=f"Built-in ignore rule {rule!r}.")
    rule = _ignore_rule(candidate, ignore)
    if rule is not None:
        return Reason(code="ignore-rule", message=f"Matches ignore rule {rule!r}.")
    return None


def _owners(hits: Iterable[ReferenceHit]) -> str:
    names: list[str] = []
    for hit in hits:
        name = hit.reference.owner or hit.reference.origin or hit.reference.path
        if name not in names:
            names.append(name)
    return ", ".join(names)


def _protected_reason(state: RefState, hits: Sequence[ReferenceHit]) -> Reason:
    owners = _owners(h for h in hits if h.reference.state is state)
    if state is RefState.RUNNING:
        return Reason(code="used-running", message=f"Used by running container(s): {owners}.")
    if state is RefState.STOPPED:
        return Reason(code="used-stopped", message=f"Used only by stopped container(s): {owners}.")
    return Reason(
        code="defined-only",
        message=f"Defined in stack/compose file(s) without a container: {owners}.",
    )


def sanity_warnings(
    candidates: Sequence[Candidate],
    references: Sequence[Reference],
    roots: Sequence[str],
    aliases: Mapping[str, str] | None = None,
) -> list[str]:
    """Detect setups that would make every folder look orphaned."""
    aliases = aliases or {}
    warnings: list[str] = []
    literal = [apply_aliases(normalize(r.path), aliases) for r in references if r.glob is None]
    for root in (normalize(r) for r in roots):
        if not any(c.root == root for c in candidates):
            continue
        if references and not any(is_under(path, root) for path in literal):
            warnings.append(
                f"No reference points into {root}. If containers do use it, the folder is "
                "probably mounted under a different path than on the host - mount it 1:1 "
                "(e.g. /opt/appdata:/opt/appdata:ro) or set PATH_ALIASES."
            )
    for ref in references:
        if ref.glob is None:
            continue
        prepared = _prepare(ref, aliases)
        if any(p.fullmatch(normalize(c.path)) for p in prepared.prefixes for c in candidates):
            continue
        # Could the unknown part stand for a folder in a scan root?
        glob = apply_aliases(normalize(ref.glob), aliases)
        tail = glob.split("*", 1)[1]
        for root in (normalize(r) for r in roots):
            if prepared.full is not None and prepared.full.fullmatch(f"{root}/\u2063{tail}"):
                warnings.append(
                    f"{ref.owner or ref.origin}: {ref.path!r} contains unresolved variables and "
                    f"may point into {root}, but matches no folder there. Make the variables "
                    "known to Dustbunny (stack env, .env) so the path can be checked."
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
    aliases: Mapping[str, str] | None = None,
    warnings: Sequence[str] = (),
) -> ScanReport:
    ok_sources = [s.name for s in sources if s.ok]
    folders = classify(
        candidates,
        references,
        roots=roots,
        ignore=ignore,
        aliases=aliases,
        checked_sources=ok_sources,
    )
    folders.sort(key=lambda f: (list(_CATEGORY_ORDER).index(f.category), f.path))

    all_warnings = list(warnings)
    if not sources:
        all_warnings.append(
            "No reference source configured - every folder would look orphaned. "
            "Configure the Docker socket, Portainer or compose directories."
        )
    for status in sources:
        if not status.ok:
            all_warnings.append(f"Source {status.name!r} failed: {status.error}")
        all_warnings.extend(f"{status.name}: {w}" for w in status.warnings)
    all_warnings.extend(sanity_warnings(candidates, references, roots, aliases))

    return ScanReport(
        roots=[normalize(r) for r in roots],
        complete=bool(sources) and all(s.ok for s in sources),
        sources=list(sources),
        warnings=list(dict.fromkeys(all_warnings)),
        summary=summarize(folders),
        folders=folders,
    )


_CATEGORY_ORDER = (
    Category.ORPHAN,
    Category.DEFINED_ONLY,
    Category.STOPPED,
    Category.ACTIVE,
    Category.IGNORED,
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
