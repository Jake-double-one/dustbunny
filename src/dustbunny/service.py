"""One scan: collect references, list folders, classify, remember, notify."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime

from dustbunny import notify
from dustbunny.collectors import Collector, run_collectors
from dustbunny.collectors.compose_files import ComposeDirsCollector
from dustbunny.collectors.docker_socket import DockerCollector, own_container_id
from dustbunny.collectors.portainer import PortainerCollector
from dustbunny.config import Settings
from dustbunny.i18n import resolve_language
from dustbunny.matcher import build_report
from dustbunny.models import Reference, ScanReport
from dustbunny.paths import apply_aliases, is_same_or_under, normalize, parse_aliases
from dustbunny.scanner import discover, validate_roots
from dustbunny.state import ScanInputs, State

log = logging.getLogger(__name__)


def configured_collectors(settings: Settings) -> list[Collector]:
    collectors: list[Collector] = []
    if settings.docker_enabled:
        collectors.append(DockerCollector(own_id=own_container_id()))
    if settings.portainer_enabled:
        assert settings.portainer_url and settings.portainer_api_key
        collectors.append(
            PortainerCollector(
                settings.portainer_url,
                settings.portainer_api_key.get_secret_value(),
                endpoint_id=settings.portainer_endpoint_id,
                verify_tls=not settings.portainer_insecure,
            )
        )
    if settings.compose_dirs:
        collectors.append(ComposeDirsCollector(settings.compose_dirs))
    return collectors


def without_own_root_mounts(
    references: list[Reference],
    roots: Sequence[str],
    own_names: set[str],
    aliases: Mapping[str, str] | None = None,
) -> list[Reference]:
    """Dustbunny's own container and stack mount the scan roots. Listing them as
    "mounts the whole scan root" next to every folder would only be noise; their
    other references (e.g. /opt/appdata/dustbunny as /data) still count."""
    if not own_names:
        return references
    return [
        ref
        for ref in references
        if ref.owner not in own_names
        or ref.glob is not None
        or not any(
            is_same_or_under(root, apply_aliases(normalize(ref.path), aliases or {}))
            for root in roots
        )
    ]


class ScanService:
    def __init__(
        self,
        settings: Settings,
        state: State,
        collectors: Callable[[], Sequence[Collector]] | None = None,
        sender: Callable[[Sequence[str], str, str], bool] = notify.send,
    ):
        self.settings = settings
        self.state = state
        self._collectors = collectors or (lambda: configured_collectors(settings))
        self._send = sender
        self._scan_lock = threading.Lock()  # one scan at a time
        self._report_lock = threading.Lock()  # report, inputs and state change together
        self._inputs: ScanInputs | None = None
        self.report: ScanReport | None = state.load_report()
        self.scanning = False
        self.last_scan_at: datetime | None = self.report.generated_at if self.report else None
        self.last_error: str | None = None
        self.config_error: str | None = None
        try:
            self.roots = validate_roots(settings.scan_roots)
            self.aliases = parse_aliases(settings.path_aliases)
        except ValueError as exc:
            self.roots, self.aliases = [], {}
            self.config_error = str(exc)
        saved = state.load_inputs()
        # after a change of SCAN_ROOTS or PATH_ALIASES the saved scan doesn't fit any more
        if saved and saved.roots == self.roots and saved.aliases == self.aliases:
            self._inputs = saved

    @property
    def ready(self) -> bool:
        return self.config_error is None

    def scan(self) -> ScanReport | None:
        """Run a full scan; returns ``None`` if one is already running."""
        if not self.ready:
            return None
        if not self._scan_lock.acquire(blocking=False):
            return None
        self.scanning = True
        try:
            started = datetime.now(UTC)
            collectors = list(self._collectors())
            references, sources = run_collectors(collectors)
            own_names: set[str] = set()
            for collector in collectors:
                own_names |= getattr(collector, "own_names", set())
            references = without_own_root_mounts(references, self.roots, own_names, self.aliases)
            discovery = discover(self.roots, with_stats=self.settings.scan_sizes)
            inputs = ScanInputs(
                candidates=discovery.candidates,
                references=references,
                sources=sources,
                warnings=discovery.warnings,
                failed_roots=discovery.failed_roots,
                roots=self.roots,
                aliases=self.aliases,
            )
            with self._report_lock:
                self._inputs = inputs
                report = self._build(inputs)
                changes = self.state.track_orphans(report)
                self.state.save_inputs(inputs)
                self.state.save_report(report)
                self.report = report
            self.last_scan_at = report.generated_at
            self.last_error = None
            log.info(
                "scan finished in %.1fs: %s folders, %s orphaned, complete=%s, uncertain=%s",
                (datetime.now(UTC) - started).total_seconds(),
                report.summary.total,
                report.summary.counts["orphan"],
                report.complete,
                report.uncertain,
            )
            self._notify(report, changes)
            return report
        except Exception as exc:
            log.exception("scan failed")
            self.last_error = str(exc) or type(exc).__name__
            raise
        finally:
            self.scanning = False
            self._scan_lock.release()

    def _build(self, inputs: ScanInputs) -> ScanReport:
        return build_report(
            inputs.candidates,
            inputs.references,
            roots=self.roots,
            sources=inputs.sources,
            ignore=self.settings.ignore,
            ignored_paths=self.state.ignored_paths(),
            aliases=self.aliases,
            warnings=inputs.warnings,
            failed_roots=inputs.failed_roots,
        )

    def set_ignored(self, path: str, ignored: bool) -> ScanReport:
        """Ignore a folder (or not) and rebuild the report without a new scan."""
        path = normalize(path)
        with self._report_lock:
            if self.report is None or path not in {f.path for f in self.report.folders}:
                raise KeyError(path)
            self.state.set_ignored(path, ignored)
            if self._inputs is None:
                return self.report  # from an older version: the next scan shows it
            report = self._build(self._inputs)
            report.generated_at = self.report.generated_at
            self.state.track_orphans(report, new_scan=False)
            self.state.save_report(report)
            self.report = report
            return report

    def _notify(self, report: ScanReport, changes: notify.OrphanChanges) -> None:
        if not self.settings.notify_urls:
            return
        message = notify.build_message(
            report,
            changes,
            mode=self.settings.notify_on,
            lang=resolve_language(self.settings.notify_language),
        )
        if message is not None:
            try:
                self._send(self.settings.notify_urls, *message)
            except Exception:
                log.exception("sending the notification failed")
