"""References from the Docker API: every container, running or stopped.

Uses ``DOCKER_HOST`` (e.g. ``tcp://socket-proxy:2375``) or the local socket.
Needed API sections: containers (list + inspect) and volumes (inspect, for
named volumes that are bound to a host folder via ``driver_opts.device``).
"""

from __future__ import annotations

import logging
import re
import socket
from typing import Any, Protocol

from dustbunny.collectors.base import CollectorResult
from dustbunny.i18n import warning
from dustbunny.models import Reference, RefState
from dustbunny.paths import normalize

log = logging.getLogger(__name__)

RUNNING_STATES = {"running", "paused", "restarting"}
LABEL_WORKING_DIR = "com.docker.compose.project.working_dir"
LABEL_CONFIG_FILES = "com.docker.compose.project.config_files"


class DockerApi(Protocol):
    """The part of ``docker.APIClient`` we use."""

    def containers(self, all: bool = ...) -> list[dict[str, Any]]: ...
    def inspect_container(self, container: str) -> dict[str, Any]: ...
    def inspect_volume(self, name: str) -> dict[str, Any]: ...


def default_client(timeout: int = 30) -> DockerApi:
    import docker  # imported late: the CLI works without the Docker SDK

    return docker.from_env(timeout=timeout).api


def own_container_id() -> str | None:
    """Inside a container the hostname is the short container id (unless set otherwise)."""
    hostname = socket.gethostname()
    return hostname if re.fullmatch(r"[0-9a-f]{12}", hostname) else None


class DockerCollector:
    name = "docker"

    def __init__(
        self, client: DockerApi | None = None, timeout: int = 30, own_id: str | None = None
    ):
        self._client = client
        self.timeout = timeout
        # Dustbunny's own container mounts the scan roots; listing it as "broad access"
        # next to every folder would only be noise.
        self.own_id = own_id

    def collect(self) -> CollectorResult:
        api = self._client or default_client(self.timeout)
        result = CollectorResult()
        volumes = _VolumeLookup(api)
        for summary in api.containers(all=True):
            if self.own_id and str(summary.get("Id", "")).startswith(self.own_id):
                continue
            try:
                info = api.inspect_container(summary["Id"])
            except Exception as exc:
                if _status(exc) == 404:  # removed between list and inspect
                    continue
                raise
            result.references.extend(self._container_references(info, volumes))
        if volumes.failed:
            names = ", ".join(sorted(volumes.failed))
            result.warnings.append(warning("docker-volumes-unavailable", volumes=names))
            result.error = f"volume details not available for: {names}"
        return result

    def _container_references(
        self, info: dict[str, Any], volumes: _VolumeLookup
    ) -> list[Reference]:
        name = str(info.get("Name") or info.get("Id", "?")[:12]).lstrip("/")
        status = str((info.get("State") or {}).get("Status", ""))
        state = RefState.RUNNING if status in RUNNING_STATES else RefState.STOPPED
        origin = f"container {name}"
        found: list[tuple[str, str, str]] = []  # (path, kind, origin)

        def add_volume(volume: str) -> None:
            device = volumes.device(volume)
            if device:
                found.append((device, "volume-device", f"{origin} (volume {volume})"))

        for mount in info.get("Mounts") or []:
            kind = mount.get("Type")
            if kind == "bind" and mount.get("Source"):
                found.append((mount["Source"], "bind", origin))
            elif kind == "volume" and mount.get("Name") and mount.get("Driver", "local") == "local":
                add_volume(mount["Name"])

        for bind in (info.get("HostConfig") or {}).get("Binds") or []:
            source = str(bind).split(":", 1)[0]
            if source.startswith("/"):
                found.append((source, "bind", origin))
            elif source:
                add_volume(source)

        labels = (info.get("Config") or {}).get("Labels") or {}
        if labels.get(LABEL_WORKING_DIR):
            found.append((labels[LABEL_WORKING_DIR], "project-dir", origin))
        for file in str(labels.get(LABEL_CONFIG_FILES) or "").split(","):
            if file.strip():
                found.append((file.strip(), "compose-file", origin))

        # Mounts and HostConfig.Binds usually report the same folder: keep it once.
        unique = dict.fromkeys((normalize(p), k, w) for p, k, w in found if p.startswith("/"))
        return [
            Reference(path=path, source=self.name, kind=kind, state=state, owner=name, origin=where)
            for path, kind, where in unique
        ]


class _VolumeLookup:
    """Looks up named volumes once per scan and remembers which lookups failed."""

    def __init__(self, api: DockerApi):
        self.api = api
        self.devices: dict[str, str | None] = {}
        self.failed: dict[str, str] = {}

    def device(self, volume: str) -> str | None:
        if volume not in self.devices and volume not in self.failed:
            try:
                self.devices[volume] = _volume_device(self.api.inspect_volume(volume))
            except Exception as exc:
                if _status(exc) == 404:
                    self.devices[volume] = None
                else:
                    self.failed[volume] = str(exc).splitlines()[0][:200]
        return self.devices.get(volume)


def _volume_device(volume: dict[str, Any]) -> str | None:
    """Host folder behind a local named volume (``driver_opts.device``), if any."""
    if volume.get("Driver", "local") != "local":
        return None
    device = (volume.get("Options") or {}).get("device")
    return device if isinstance(device, str) and device.startswith("/") else None


def _status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else getattr(exc, "status_code", None)
