"""Command line entry point.

``dustbunny`` starts the web server (web UI, API, periodic scan).
``dustbunny --once`` runs a single scan with the configured sources and
prints the report.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from dustbunny import __version__
from dustbunny.collectors import Collector, run_collectors
from dustbunny.collectors.compose_files import ComposeFilesCollector
from dustbunny.collectors.static import StaticCollector
from dustbunny.config import Settings
from dustbunny.matcher import build_report, literal_paths
from dustbunny.models import ScanReport
from dustbunny.notify import format_size
from dustbunny.paths import parse_aliases
from dustbunny.scanner import discover, validate_roots
from dustbunny.service import configured_collectors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dustbunny",
        description="Find orphaned Docker appdata folders. Without --once, the web server starts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--once", action="store_true", help="run a single scan and exit")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--root", action="append", default=[], metavar="PATH",
        help="scan root (repeatable; default: SCAN_ROOTS)",
    )  # fmt: skip
    parser.add_argument(
        "--ignore", action="append", default=[], metavar="GLOB",
        help="ignore folders matching GLOB (repeatable; added to IGNORE)",
    )  # fmt: skip
    parser.add_argument(
        "--alias", action="append", default=[], metavar="HOST=LOCAL",
        help="translate host paths to local paths (repeatable; added to PATH_ALIASES)",
    )  # fmt: skip
    parser.add_argument(
        "--references", action="append", default=[], metavar="FILE",
        help="JSON file with extra references (repeatable)",
    )  # fmt: skip
    parser.add_argument(
        "--compose", action="append", default=[], metavar="FILE",
        help="compose file whose paths count as references (repeatable)",
    )  # fmt: skip
    parser.add_argument(
        "--no-docker", action="store_true", help="don't ask the Docker API (DOCKER_ENABLED=false)"
    )
    parser.add_argument("--no-size", action="store_true", help="skip size/age calculation")
    parser.add_argument("-o", "--output", metavar="FILE", help="write the report to FILE")
    return parser


def run_once(args: argparse.Namespace, settings: Settings) -> ScanReport:
    roots = validate_roots(args.root or settings.scan_roots)
    aliases = parse_aliases([*settings.path_aliases, *args.alias])
    ignore = [*settings.ignore, *args.ignore]

    if args.no_docker:
        settings = settings.model_copy(update={"docker_enabled": False})
    collectors: list[Collector] = configured_collectors(settings)
    if args.references:
        collectors.append(StaticCollector(args.references))
    if args.compose:
        collectors.append(ComposeFilesCollector(args.compose))

    references, sources = run_collectors(collectors)
    discovery = discover(
        roots,
        with_stats=settings.scan_sizes and not args.no_size,
        tracked=literal_paths(references, aliases),
    )
    return build_report(
        discovery.candidates,
        references,
        roots=roots,
        sources=sources,
        ignore=ignore,
        aliases=aliases,
        warnings=discovery.warnings,
    )


def format_text(report: ScanReport) -> str:
    lines: list[str] = []
    width = max((len(f.path) for f in report.folders), default=4)
    lines.append(f"{'CATEGORY':<13} {'SIZE':>10}  {'PATH':<{width}}  REASON")
    for folder in report.folders:
        reason = folder.reasons[0].message if folder.reasons else ""
        lines.append(
            f"{folder.category.value:<13} {format_size(folder.size_bytes):>10}  "
            f"{folder.path:<{width}}  {reason}"
        )
    counts = ", ".join(f"{c.value}: {n}" for c, n in report.summary.counts.items() if n)
    lines.append("")
    lines.append(
        f"{report.summary.total} folders ({counts or 'none'}); "
        f"orphaned: {format_size(report.summary.orphan_bytes)}"
    )
    if not report.complete:
        lines.append("WARNING: incomplete result - orphaned folders may be wrong.")
    lines.extend(f"warning: {w.message}" for w in report.warnings)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"dustbunny: configuration error: {exc}", file=sys.stderr)
        return 2

    if not args.once:
        from dustbunny.server import serve

        serve(settings)
        return 0

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        report = run_once(args, settings)
    except ValueError as exc:
        print(f"dustbunny: error: {exc}", file=sys.stderr)
        return 2

    output = report.model_dump_json(indent=2) if args.json else format_text(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(output + "\n")
    else:
        print(output)
    return 0
