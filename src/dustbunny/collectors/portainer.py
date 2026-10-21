"""References from Portainer stacks - including stopped stacks, whose
containers are gone but whose data is still needed."""

from __future__ import annotations

from typing import Any

import httpx

from dustbunny.collectors.base import CollectorResult
from dustbunny.compose_parser import parse_compose
from dustbunny.i18n import warning
from dustbunny.models import RefState


class PortainerError(RuntimeError):
    pass


class PortainerCollector:
    name = "portainer"

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        endpoint_id: int | None = None,
        verify_tls: bool = True,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.url,
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            verify=self.verify_tls,
            timeout=self.timeout,
            transport=self.transport,
        )

    def collect(self) -> CollectorResult:
        result = CollectorResult()
        with self._client() as client:
            stacks = _get(client, "/api/stacks")
            if not isinstance(stacks, list):
                raise PortainerError("unexpected answer from /api/stacks")
            for stack in stacks:
                if self.endpoint_id is not None and stack.get("EndpointId") != self.endpoint_id:
                    continue
                self._collect_stack(client, stack, result)
        return result

    def _collect_stack(self, client: httpx.Client, stack: dict[str, Any], result: CollectorResult):
        stack_id = stack.get("Id")
        name = str(stack.get("Name") or f"stack {stack_id}")
        content = _get(client, f"/api/stacks/{stack_id}/file").get("StackFileContent") or ""
        env = {
            str(item["name"]): str(item.get("value", ""))
            for item in stack.get("Env") or []
            if isinstance(item, dict) and item.get("name")
        }
        parsed = parse_compose(
            content,
            env=env,
            base_dir=None,  # relative paths point into Portainer's own /data/compose
            source=self.name,
            owner=name,
            origin=f"Portainer stack {name}",
            state=RefState.DEFINED,
        )
        result.references.extend(parsed.references)
        result.warnings.extend(parsed.warnings)
        if stack.get("AdditionalFiles"):
            result.warnings.append(warning("portainer-additional-files", stack=name))


def _get(client: httpx.Client, path: str) -> Any:
    try:
        response = client.get(path)
    except httpx.HTTPError as exc:
        raise PortainerError(f"cannot reach Portainer: {exc}") from exc
    if response.status_code in (401, 403):
        raise PortainerError(f"Portainer refused the API key ({response.status_code})")
    if response.status_code >= 400:
        raise PortainerError(f"{path}: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise PortainerError(f"{path}: no JSON in the answer - is PORTAINER_URL right?") from exc
