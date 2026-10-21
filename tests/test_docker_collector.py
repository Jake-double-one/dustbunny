from __future__ import annotations

import json
from pathlib import Path

import pytest

from dustbunny.collectors.docker_socket import DockerCollector
from dustbunny.models import RefState


class FakeError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class FakeApi:
    def __init__(self, fixtures: Path, forbid_volumes: bool = False):
        self._containers = json.loads((fixtures / "docker" / "containers.json").read_text())
        self._volumes = json.loads((fixtures / "docker" / "volumes.json").read_text())
        self.forbid_volumes = forbid_volumes

    def containers(self, all: bool = False):
        assert all is True
        return [{"Id": c["Id"]} for c in self._containers]

    def inspect_container(self, container: str):
        info = next(c for c in self._containers if c["Id"] == container)
        if info["Name"] == "/gone":
            raise FakeError(404)
        return info

    def inspect_volume(self, name: str):
        if self.forbid_volumes:
            raise FakeError(403)
        if name not in self._volumes:
            raise FakeError(404)
        return self._volumes[name]


def refs_by(result, kind):
    return {(r.path, r.owner, r.state) for r in result.references if r.kind == kind}


def test_docker_collector(fixtures: Path) -> None:
    result = DockerCollector(FakeApi(fixtures)).collect()
    assert result.error is None
    assert refs_by(result, "bind") >= {
        ("/opt/appdata/sonarr", "sonarr", RefState.RUNNING),
        ("/mnt/media/tv", "sonarr", RefState.RUNNING),
        ("/opt/appdata/legacy/data", "legacy", RefState.RUNNING),  # paused counts as running
    }
    # named volume bound to a host folder, container stopped
    assert refs_by(result, "volume-device") == {
        ("/opt/appdata/nextcloud/db", "nextcloud-db", RefState.STOPPED)
    }
    assert refs_by(result, "project-dir") == {("/opt/stacks/media", "sonarr", RefState.RUNNING)}
    assert {p for p, _, _ in refs_by(result, "compose-file")} == {
        "/opt/stacks/media/compose.yaml",
        "/opt/stacks/media/compose.override.yaml",
    }
    # NFS device and container paths are no host folders
    assert not any("export" in r.path for r in result.references)
    assert all(r.source == "docker" for r in result.references)
    sonarr = [r.path for r in result.references if r.owner == "sonarr" and r.kind == "bind"]
    assert sorted(sonarr) == ["/mnt/media/tv", "/opt/appdata/sonarr"]  # Mounts + Binds: once


def test_forbidden_volume_api_marks_source_incomplete(fixtures: Path) -> None:
    result = DockerCollector(FakeApi(fixtures, forbid_volumes=True)).collect()
    assert result.error is not None
    assert result.warnings[0].code == "docker-volumes-unavailable"
    assert "nc_db" in result.warnings[0].params["volumes"]
    # bind mounts still count
    assert ("/opt/appdata/sonarr", "sonarr", RefState.RUNNING) in refs_by(result, "bind")


def test_other_errors_propagate(fixtures: Path) -> None:
    api = FakeApi(fixtures)

    def broken(container: str):
        raise FakeError(500)

    api.inspect_container = broken  # type: ignore[method-assign]
    with pytest.raises(FakeError):
        DockerCollector(api).collect()


def test_own_container_is_skipped(fixtures: Path) -> None:
    result = DockerCollector(FakeApi(fixtures), own_id="aaa111").collect()
    assert not any(r.owner == "sonarr" for r in result.references)
