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

FOLDERS = {  # name: (size, last change days ago, first seen as orphan days ago, created days ago)
    "jellyfin": (8.4 * GIB, 0, None, 700),
    "sonarr": (1.2 * GIB, 0, None, 650),
    "radarr": (940 * MIB, 0, None, 640),
    "nextcloud": (3.1 * GIB, 41, None, 500),
    "paperless": (2.3 * GIB, 96, None, 420),
    "immich-old": (6.2 * GIB, 212, 23, 380),
    "wikijs-test": (310 * MIB, 140, 61, 200),
    "heimdall": (48 * MIB, 30, 2, 90),
    "backup-2024": (12.5 * GIB, 300, None, 310),
    "lost+found": (16 * 1024, 900, None, 900),
}

PATH_SIZES = {  # referenced paths inside the folders
    "/opt/appdata/jellyfin/config": int(1.1 * GIB),
    "/opt/appdata/jellyfin/cache": int(7.2 * GIB),
    "/opt/appdata/nextcloud/html": int(2.6 * GIB),
    "/opt/appdata/nextcloud/db": 480 * MIB,
    "/opt/appdata/paperless/data": 210 * MIB,
    "/opt/appdata/paperless/media": int(2.1 * GIB),
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
    for name, (size, changed, _, created) in FOLDERS.items():
        candidates.append(
            Candidate(
                path=f"{ROOT}/{name}",
                root=ROOT,
                name=name,
                size_bytes=int(size),
                last_modified=NOW - timedelta(days=changed, hours=3),
                created=NOW - timedelta(days=created),
                path_sizes={p: v for p, v in PATH_SIZES.items() if p.startswith(f"{ROOT}/{name}/")},
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
