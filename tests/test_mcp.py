from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dustbunny.collectors.static import StaticCollector
from dustbunny.config import Settings
from dustbunny.server import create_app
from dustbunny.service import ScanService
from dustbunny.state import State
from tests.test_server import env, wait_for_report  # noqa: F401 - env is a fixture

TOKEN = "t" * 32


def make(env, **overrides):  # noqa: F811
    root, refs, tmp = env
    settings = Settings(
        scan_roots=[str(root)],
        data_dir=tmp / "data",
        scan_interval="0",
        docker_enabled=False,
        mcp_enabled=True,
        mcp_token=TOKEN,
        **overrides,
    )
    service = ScanService(
        settings,
        State(settings.data_dir / "db.sqlite3"),
        collectors=lambda: [StaticCollector([refs])],
    )
    return settings, service


def rpc(client: TestClient, method: str, params: dict | None = None, *, msg_id: int = 1, **kw):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    response = client.post(f"/mcp/{TOKEN}", json=body, **kw)
    assert response.status_code == 200, response.text
    return response.json()


def call(client: TestClient, tool: str, **arguments) -> dict:
    return rpc(client, "tools/call", {"name": tool, "arguments": arguments})["result"]


def test_handshake_and_tools(env) -> None:  # noqa: F811
    settings, service = make(env)
    with TestClient(create_app(settings, service)) as client:
        wait_for_report(client)
        init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        assert init["result"]["protocolVersion"] == "2025-06-18"
        assert init["result"]["serverInfo"]["name"] == "dustbunny"
        assert "tools" in init["result"]["capabilities"]
        newest = rpc(client, "initialize", {"protocolVersion": "1999-01-01"})["result"]
        assert newest["protocolVersion"] == "2025-11-25"

        notification = client.post(
            f"/mcp/{TOKEN}", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert notification.status_code == 202

        tools = {t["name"]: t for t in rpc(client, "tools/list")["result"]["tools"]}
        assert set(tools) == {"get_summary", "list_folders", "get_folder", "start_scan"}
        assert all(t["annotations"]["readOnlyHint"] for t in tools.values())

        summary = call(client, "get_summary")["structuredContent"]
        assert summary["counts"]["orphan"] == 1 and summary["complete"]

        by_name = call(client, "list_folders", sort="name")["structuredContent"]
        assert [f["name"] for f in by_name["folders"]] == ["old", "used"]
        assert "created" in by_name["folders"][0]
        assert call(client, "list_folders", sort="weird")["isError"]

        orphans = call(client, "list_folders", category="orphan")["structuredContent"]
        assert [f["name"] for f in orphans["folders"]] == ["old"]
        assert orphans["folders"][0]["orphaned_since"]

        detail = call(client, "get_folder", folder="used")["structuredContent"]
        assert detail["category"] == "active"
        assert detail["used_by"][0]["owner"] == "app"
        assert detail["used_by"][0]["size_bytes"] == detail["size_bytes"]

        missing = call(client, "get_folder", folder="nope")
        assert missing["isError"] and "list_folders" in missing["content"][0]["text"]

        assert call(client, "start_scan")["structuredContent"]["started"] in (True, False)
        assert rpc(client, "ping")["result"] == {}


def test_changes_need_permission(env) -> None:  # noqa: F811
    settings, service = make(env)
    with TestClient(create_app(settings, service)) as client:
        wait_for_report(client)
        result = rpc(client, "tools/call", {"name": "set_folder_ignored", "arguments": {}})
        assert result["error"]["code"] == -32602

    settings, service = make(env, mcp_allow_changes=True)
    with TestClient(create_app(settings, service)) as client:
        wait_for_report(client)
        tools = {t["name"]: t for t in rpc(client, "tools/list")["result"]["tools"]}
        assert tools["set_folder_ignored"]["annotations"]["readOnlyHint"] is False
        result = call(client, "set_folder_ignored", folder="old", ignored=True)
        assert result["structuredContent"]["category"] == "ignored"
        assert client.get("/api/report").json()["summary"]["counts"]["orphan"] == 0


def test_key_is_required(env) -> None:  # noqa: F811
    settings, service = make(env, auth_user="admin", auth_password="secret")
    with TestClient(create_app(settings, service)) as client:
        body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        assert client.post("/mcp/wrong-key-wrong-key-wrong-key", json=body).status_code == 404
        assert client.post("/mcp", json=body).status_code == 404
        bearer = {"Authorization": f"Bearer {TOKEN}"}
        assert client.post("/mcp", json=body, headers=bearer).status_code == 200
        # the MCP key replaces Basic Auth for /mcp, nothing else
        assert client.post(f"/mcp/{TOKEN}", json=body).status_code == 200
        assert client.get("/api/report").status_code == 401
        assert client.get(f"/mcp/{TOKEN}").status_code == 405
        evil = {"Origin": "https://evil.example"}
        assert client.post(f"/mcp/{TOKEN}", json=body, headers=evil).status_code == 403


def test_protocol_errors(env) -> None:  # noqa: F811
    settings, service = make(env)
    with TestClient(create_app(settings, service)) as client:
        assert rpc(client, "nope")["error"]["code"] == -32601
        bad = client.post(
            f"/mcp/{TOKEN}", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert bad.json()["error"]["code"] == -32700
        assert rpc(client, "tools/call", {"name": "x"})["error"]["code"] == -32602


def test_off_by_default(tmp_path: Path) -> None:
    settings = Settings(scan_roots=["/tmp"], data_dir=tmp_path, docker_enabled=False)
    with TestClient(create_app(settings)) as client:
        assert client.post("/mcp", json={}).status_code == 404


@pytest.mark.parametrize("token", [None, "short", "x" * 30 + "/"])
def test_enabling_needs_a_good_token(token) -> None:
    with pytest.raises(ValueError, match="MCP_TOKEN"):
        Settings(mcp_enabled=True, mcp_token=token)
