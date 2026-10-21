"""Data models shared by collectors, matcher, API and the report."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

REPORT_SCHEMA_VERSION = 1


class RefState(StrEnum):
    """How alive the thing behind a reference is."""

    RUNNING = "running"  # a running (or paused/restarting) container
    STOPPED = "stopped"  # a container exists but is not running
    DEFINED = "defined"  # only a stack/compose definition, no container


class Category(StrEnum):
    """Folder categories. UI labels: see ``category.*`` in ``locales/*.json``."""

    ACTIVE = "active"
    STOPPED = "stopped"
    DEFINED_ONLY = "defined-only"
    ORPHAN = "orphan"
    IGNORED = "ignored"


class Relation(StrEnum):
    EXACT = "exact"  # reference points at the folder itself
    INSIDE = "inside"  # reference points at something inside the folder
    BROAD = "broad"  # reference covers the whole scan root (or more)


class Reference(BaseModel):
    """A host path that something still uses or defines."""

    path: str = Field(description="Host path as reported/defined (for display).")
    source: str = Field(description="Collector that produced it, e.g. docker, portainer.")
    kind: str = Field(default="bind", description="bind, volume-device, env-file, raw-text, ...")
    state: RefState = RefState.DEFINED
    owner: str | None = Field(default=None, description="Container, stack or project name.")
    origin: str | None = Field(default=None, description="File, container id or API object.")
    glob: str | None = Field(
        default=None,
        description="Set when parts of the path could not be resolved; '*' marks unknown parts.",
    )

    @property
    def is_pattern(self) -> bool:
        return self.glob is not None


class Candidate(BaseModel):
    """A direct subfolder of a scan root."""

    path: str
    root: str
    name: str
    real_path: str | None = None
    is_symlink: bool = False
    link_target: str | None = Field(default=None, description="Where a symlink points to.")
    is_mountpoint: bool = False
    size_bytes: int | None = None
    last_modified: datetime | None = None
    stats_complete: bool = True


class Notice(BaseModel):
    """A reason or warning. ``code`` + ``params`` are for translation (see
    ``locales/*.json``), ``message`` is the English text for API and CLI users."""

    code: str
    message: str
    params: dict[str, str] = Field(default_factory=dict)


class ReferenceHit(BaseModel):
    reference: Reference
    relation: Relation
    matched_path: str


class FolderResult(BaseModel):
    path: str
    root: str
    name: str
    category: Category
    reasons: list[Notice] = Field(default_factory=list)
    protected_by: list[ReferenceHit] = Field(default_factory=list)
    broad_access: list[ReferenceHit] = Field(default_factory=list)
    checked_sources: list[str] = Field(default_factory=list)
    size_bytes: int | None = None
    last_modified: datetime | None = None
    stats_complete: bool = True
    is_symlink: bool = False
    is_mountpoint: bool = False
    first_seen: datetime | None = Field(
        default=None, description="When Dustbunny first saw this folder orphaned."
    )


class SourceStatus(BaseModel):
    name: str
    ok: bool = True
    error: str | None = None
    reference_count: int = 0
    warnings: list[Notice] = Field(default_factory=list)


class Summary(BaseModel):
    total: int = 0
    counts: dict[Category, int] = Field(default_factory=lambda: {c: 0 for c in Category})
    total_bytes: int = 0
    orphan_bytes: int = 0


class ScanReport(BaseModel):
    schema_version: int = REPORT_SCHEMA_VERSION
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    roots: list[str]
    complete: bool = Field(
        description="False if a reference source failed, none was configured or a scan "
        "root could not be read."
    )
    uncertain: bool = Field(
        default=False,
        description="True if some paths could not be checked fully (unknown variables, "
        "unreadable compose files). See the warnings.",
    )
    sources: list[SourceStatus]
    warnings: list[Notice] = Field(default_factory=list)
    summary: Summary
    folders: list[FolderResult]

    @property
    def reliable(self) -> bool:
        """Only a reliable report may notify or change what Dustbunny remembers."""
        return self.complete and not self.uncertain
