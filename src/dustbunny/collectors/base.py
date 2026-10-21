from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from dustbunny.models import Reference, SourceStatus

log = logging.getLogger(__name__)


@dataclass
class CollectorResult:
    references: list[Reference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
            log.exception("collector %s failed", collector.name)
            statuses.append(SourceStatus(name=collector.name, ok=False, error=str(exc)))
            continue
        references.extend(result.references)
        statuses.append(
            SourceStatus(
                name=collector.name,
                reference_count=len(result.references),
                warnings=result.warnings,
            )
        )
    return references, statuses
