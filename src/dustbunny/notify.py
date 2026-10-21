"""Notifications through Apprise (ntfy, Discord, e-mail, Telegram, ...).

Only complete reports notify: a failed source must not announce orphans.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from dustbunny.i18n import translate
from dustbunny.models import Category, ScanReport
from dustbunny.state import OrphanChanges

log = logging.getLogger(__name__)
MAX_LINES = 15


def format_size(size: int | None, lang: str = "en") -> str:
    if size is None:
        return "-"
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            number = f"{value:.0f}" if unit == "B" else f"{value:.1f}"
            return f"{number.replace('.', translate('format.decimal', lang))} {unit}"
        value /= 1024
    raise AssertionError  # pragma: no cover


def build_message(
    report: ScanReport, changes: OrphanChanges, *, mode: str, lang: str
) -> tuple[str, str] | None:
    """Title and body, or ``None`` if there is nothing to say."""
    if not report.reliable:
        return None
    if mode != "always" and not changes.changed:
        return None

    def t(key: str, **params: object) -> str:
        return translate(key, lang, **params)

    count = report.summary.counts[Category.ORPHAN]
    total = format_size(report.summary.orphan_bytes, lang)
    if changes.first_scan:
        title = t("notify.title-first", count=count)
    elif changes.new:
        title = t("notify.title-new", count=len(changes.new))
    elif changes.resolved:
        title = t("notify.title-resolved", count=len(changes.resolved))
    else:
        title = t("notify.title-summary", count=count)

    lines: list[str] = []
    if changes.new:
        lines.append(t("notify.first-heading" if changes.first_scan else "notify.new-heading"))
        for folder in changes.new[:MAX_LINES]:
            lines.append(f"• {folder.path} ({format_size(folder.size_bytes, lang)})")
        if len(changes.new) > MAX_LINES:
            lines.append(t("notify.more", count=len(changes.new) - MAX_LINES))
    if changes.resolved:
        lines.append(t("notify.resolved-heading"))
        for path, folder in changes.resolved[:MAX_LINES]:
            if folder is None:
                state = t("notify.state-removed")
            else:
                state = t(f"category.{folder.category.value}")
            lines.append(f"• {path} ({state})")
        if len(changes.resolved) > MAX_LINES:
            lines.append(t("notify.more", count=len(changes.resolved) - MAX_LINES))
    lines.append(t("notify.total", count=count, size=total))
    return title, "\n".join(lines)


def send(urls: Sequence[str], title: str, body: str) -> bool:
    if not urls:
        return False
    import apprise  # imported late: optional for the CLI

    client = apprise.Apprise()
    for url in urls:
        if not client.add(url):
            log.warning("notification URL not understood by Apprise: %s", _redact(url))
    if not len(client):
        return False
    ok = bool(client.notify(title=title, body=body))
    if not ok:
        log.warning("sending the notification failed")
    return ok


def _redact(url: str) -> str:
    scheme, sep, _ = url.partition("://")
    return f"{scheme}://…" if sep else "…"
