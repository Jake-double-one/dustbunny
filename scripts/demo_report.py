"""Write a realistic demo report for UI work and screenshots.

python scripts/demo_report.py > src/dustbunny/web/static/demo/report.json
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from dustbunny.matcher import build_report
from dustbunny.models import Candidate, Category, Reference, RefState, SourceStatus

ROOT = "/opt/appdata"
NOW = datetime(2026, 10, 21, 7, 42, tzinfo=UTC)
GIB, MIB = 1024**3, 1024**2

FOLDERS = {  # name: (size, last change days ago, first seen as orphan days ago)
    "jellyfin": (8.4 * GIB, 0, None),
    "sonarr": (1.2 * GIB, 0, None),
    "radarr": (940 * MIB, 0, None),
    "nextcloud": (3.1 * GIB, 41, None),
    "paperless": (2.3 * GIB, 96, None),
    "immich-old": (6.2 * GIB, 212, 23),
    "wikijs-test": (310 * MIB, 140, 61),
    "heimdall": (48 * MIB, 30, 2),
    "backup-2024": (12.5 * GIB, 300, None),
    "lost+found": (16 * 1024, 900, None),
}


def ref(path: str, state: RefState, owner: str, source: str, kind: str = "bind") -> Reference:
    return Reference(path=path, source=source, kind=kind, state=state, owner=owner)


REFERENCES = [
    ref("/opt/appdata/jellyfin/config", RefState.RUNNING, "jellyfin", "docker"),
    ref("/opt/appdata/jellyfin/cache", RefState.RUNNING, "jellyfin", "docker"),
    ref("/opt/appdata/sonarr", RefState.RUNNING, "sonarr", "docker"),
    ref("/opt/appdata/radarr", RefState.RUNNING, "radarr", "docker"),
    ref("/opt/appdata/nextcloud/html", RefState.STOPPED, "nextcloud-app", "docker"),
    ref("/opt/appdata/nextcloud/db", RefState.STOPPED, "nextcloud-db", "docker"),
    ref("/opt/appdata/nextcloud/html", RefState.DEFINED, "nextcloud", "portainer"),
    ref("/opt/appdata/paperless/data", RefState.DEFINED, "paperless", "portainer"),
    ref("/opt/appdata/paperless/media", RefState.DEFINED, "paperless", "portainer"),
    ref("/opt/appdata", RefState.RUNNING, "duplicati", "docker"),
    Reference(
        path="${DATA}/grafana",
        glob="*/grafana",
        source="portainer",
        state=RefState.DEFINED,
        owner="monitoring",
    ),
]


def main() -> None:
    candidates = []
    for name, (size, changed, _) in FOLDERS.items():
        candidates.append(
            Candidate(
                path=f"{ROOT}/{name}",
                root=ROOT,
                name=name,
                size_bytes=int(size),
                last_modified=NOW - timedelta(days=changed, hours=3),
            )
        )
    sources = [
        SourceStatus(name="docker", reference_count=7),
        SourceStatus(name="portainer", reference_count=4),
    ]
    report = build_report(
        candidates,
        REFERENCES,
        roots=[ROOT],
        sources=sources,
        ignore=["backup-*"],
    )
    report.generated_at = NOW
    for folder in report.folders:
        first_seen = FOLDERS[folder.name][2]
        if folder.category is Category.ORPHAN and first_seen is not None:
            folder.first_seen = NOW - timedelta(days=first_seen)
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
