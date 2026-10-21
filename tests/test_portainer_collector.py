from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from dustbunny.collectors.portainer import PortainerCollector, PortainerError
from dustbunny.models import RefState


def transport(fixtures: Path, *, status: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"message": "nope"})
        path = request.url.path
        if path == "/api/stacks":
            return httpx.Response(
                200, content=(fixtures / "portainer" / "stacks.json").read_bytes()
            )
        stack_id = path.split("/")[3]
        file = fixtures / "portainer" / f"stack_{stack_id}_file.json"
        return httpx.Response(200, content=file.read_bytes())

    return httpx.MockTransport(handler)


def collector(fixtures: Path, **kwargs) -> PortainerCollector:
    seen = kwargs.pop("seen", None)
    status = kwargs.pop("status", 200)
    return PortainerCollector(
        "https://portainer.example:9443/",
        "ptr_key",
        transport=transport(fixtures, status=status, seen=seen),
        **kwargs,
    )


def test_portainer_stacks(fixtures: Path) -> None:
    seen: list[httpx.Request] = []
    result = collector(fixtures, seen=seen).collect()
    binds = {(r.path, r.owner) for r in result.references if r.kind == "bind"}
    assert ("/opt/appdata/sonarr", "media") in binds  # env from the stack
    assert ("/opt/appdata/paperless/data", "paperless") in binds  # stopped stack
    assert ("/opt/appdata/x", "other-host") in binds  # no endpoint filter
    assert all(r.state is RefState.DEFINED and r.source == "portainer" for r in result.references)
    # unknown variable -> pattern, relative path -> skipped with a warning
    assert any(r.glob == "*/paperless" for r in result.references)
    codes = [w.code for w in result.warnings]
    assert "compose-relative-path" in codes
    assert "portainer-additional-files" in codes
    assert seen[0].headers["X-API-Key"] == "ptr_key"
    assert str(seen[0].url) == "https://portainer.example:9443/api/stacks"


def test_endpoint_filter(fixtures: Path) -> None:
    result = collector(fixtures, endpoint_id=2).collect()
    assert {r.owner for r in result.references} == {"media", "paperless"}


@pytest.mark.parametrize(("status", "text"), [(401, "API key"), (500, "HTTP 500")])
def test_errors(fixtures: Path, status: int, text: str) -> None:
    with pytest.raises(PortainerError, match=text):
        collector(fixtures, status=status).collect()


def test_not_json(fixtures: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    c = PortainerCollector("https://x", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(PortainerError, match="PORTAINER_URL"):
        c.collect()


def test_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    c = PortainerCollector("https://x", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(PortainerError, match="cannot reach"):
        c.collect()
