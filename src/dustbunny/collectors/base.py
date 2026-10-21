from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from dustbunny.models import Notice, Reference, SourceStatus

log = logging.getLogger(__name__)


@dataclass
class CollectorResult:
    references: list[Reference] = field(default_factory=list)
    warnings: list[Notice] = field(default_factory=list)
    # Set when the source answered only partly: its references are used, but
    # the report is marked incomplete because something may be missing.
    error: str | None = None


class Collector(Protocol):
    name: str

    def collect(self) -> CollectorResult: ...


def run_collectors(
    collectors: Iterable[Collector],
) -> tuple[list[Reference], list[SourceStatus]]:
    """Run all collectors. A failing collector marks its source as not ok
    instead of aborting the scan, so the report can be flagged incomplete."""
    references: list[Reference] = []
    statuses: list[SourceStatus] = []
    for collector in collectors:
        try:
            result = collector.collect()
        except Exception as exc:  # any failure makes the source unreliable
            log.warning("source %s failed: %s", collector.name, exc, exc_info=log.isEnabledFor(10))
            statuses.append(SourceStatus(name=collector.name, ok=False, error=_describe(exc)))
            continue
        references.extend(result.references)
        statuses.append(
            SourceStatus(
                name=collector.name,
                ok=result.error is None,
                error=result.error,
                reference_count=len(result.references),
                warnings=result.warnings,
            )
        )
    return references, statuses


def _describe(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text.splitlines()[0][:300]
