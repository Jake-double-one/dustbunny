from __future__ import annotations

import base64
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dustbunny import __version__
from dustbunny.collectors.static import StaticCollector
from dustbunny.config import Settings
from dustbunny.server import create_app
from dustbunny.service import ScanService
from dustbunny.state import State


@pytest.fixture
def env(tmp_path: Path):
    root = tmp_path / "appdata"
    for name in ("used", "old"):
        (root / name).mkdir(parents=True)
    refs = tmp_path / "refs.json"
    refs.write_text(f'[{{"path": "{root}/used", "state": "running", "owner": "app"}}]')
    return root, refs, tmp_path


def make(env, **overrides):
    root, refs, tmp = env
    settings = Settings(
        scan_roots=[str(root)],
        data_dir=tmp / "data",
        scan_interval="0",
        docker_enabled=False,
        **overrides,
    )
    service = ScanService(
        settings,
        State(settings.data_dir / "db.sqlite3"),
        collectors=lambda: [StaticCollector([refs])],
    )
    return settings, service


def wait_for_report(client: TestClient) -> dict:
    for _ in range(100):
        response = client.get("/api/report")
        if response.status_code == 200 and not client.get("/api/status").json()["scanning"]:
            return response.json()
        time.sleep(0.05)
    raise AssertionError("no report")


def test_full_flow(env) -> None:
    settings, service = make(env)
    with TestClient(create_app(settings, service)) as client:
        report = wait_for_report(client)
        cats = {f["name"]: f["category"] for f in report["folders"]}
        assert cats == {"used": "active", "old": "orphan"}
        old = next(f for f in report["folders"] if f["name"] == "old")
        assert old["first_seen"] is not None

        r = client.post("/api/ignore", json={"path": old["path"], "ignored": True})
        assert r.status_code == 200
        folder = next(f for f in r.json()["folders"] if f["name"] == "old")
        assert folder["category"] == "ignored"
        assert folder["reasons"][0]["code"] == "ignored-by-user"
        r = client.post("/api/ignore", json={"path": old["path"], "ignored": False})
        assert next(f for f in r.json()["folders"] if f["name"] == "old")["category"] == "orphan"
        assert client.post("/api/ignore", json={"path": "/etc", "ignored": True}).status_code == 404

        assert client.post("/api/scan", json={}).status_code == 202
        # a plain form post (what another web page could send) is refused
        assert client.post("/api/scan", data={"x": "1"}).status_code == 415
        status = client.get("/api/status").json()
        assert status["roots"] == [str(env[0])] and status["config_error"] is None


def test_page_assets_and_headers(env) -> None:
    settings, service = make(env)
    with TestClient(create_app(settings, service)) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert '<style id="skins">' in page.text and 'id="skin-list"' in page.text
        ids = re.findall(r'id="([^"]+)"', page.text)
        assert len(ids) == len(set(ids)), "duplicate element ids"
        assert 'id="boot"' in page.text and '"code": "de"' in page.text
        assert "<!--" not in page.text.split("<body>")[0].replace("<!-- ", "")
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert client.get("/static/app.js").status_code == 200
        # CSS and JS are linked under the version and must be revalidated
        css = re.search(r'href="(static/[^"]+/app\.css)"', page.text).group(1)
        assert css == f"static/{__version__.replace('+', '-')}/app.css"
        assert 'src="static/' in page.text and 'src="static/app.js"' not in page.text
        styles = client.get(f"/{css}")
        assert styles.status_code == 200 and styles.headers["cache-control"] == "no-cache"
        again = client.get(f"/{css}", headers={"If-None-Match": styles.headers["etag"]})
        assert again.status_code == 304
        assert client.get(f"/{css.rsplit('/', 1)[0]}/i18n.js").status_code == 200
        assert client.get("/static/fonts/ibm-plex-mono-latin-400-normal.woff2").status_code == 200
        assert client.get("/locales/de.json").json()["category.orphan"] == "Verwaist"
        assert client.get("/locales/xx.json").status_code == 404
        assert client.get("/locales/..%2fconfig.json").status_code == 404
        skins = client.get("/api/skins").json()
        assert [s["id"] for s in skins["skins"]][:2] == ["dark", "amoled"]
        assert client.get("/api/languages").json()[0] == {"code": "en", "name": "English"}


def test_basic_auth(env) -> None:
    settings, service = make(env, auth_user="admin", auth_password="s3cret")
    with TestClient(create_app(settings, service)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/").status_code == 401
        assert client.get("/").headers["x-frame-options"] == "DENY"
        assert client.get("/api/report").headers["www-authenticate"].startswith("Basic")
        bad = base64.b64encode(b"admin:wrong").decode()
        assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
        good = base64.b64encode(b"admin:s3cret").decode()
        assert client.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200


def test_config_error_is_shown_not_fatal(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, scan_interval="0", docker_enabled=False)
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/status").json()
        assert "SCAN_ROOTS" in status["config_error"]
        assert client.get("/api/report").status_code == 404
        assert client.post("/api/scan", json={}).status_code == 409
        assert client.get("/healthz").json()["status"] == "ok"


def test_scan_request_runs_another_scan(env) -> None:
    root, refs, tmp = env
    calls = []

    class Counting(StaticCollector):
        def collect(self):
            calls.append(1)
            return super().collect()

    settings = Settings(
        scan_roots=[str(root)], data_dir=tmp / "data", scan_interval="0", docker_enabled=False
    )
    service = ScanService(
        settings, State(settings.data_dir / "db.sqlite3"), collectors=lambda: [Counting([refs])]
    )
    with TestClient(create_app(settings, service)) as client:
        wait_for_report(client)
        assert len(calls) == 1
        assert client.post("/api/scan", json={}).status_code == 202
        for _ in range(100):
            if len(calls) == 2 and not client.get("/api/status").json()["scanning"]:
                break
            time.sleep(0.05)
        assert len(calls) == 2


def test_serve_logs_the_version(tmp_path: Path, monkeypatch, caplog) -> None:
    import uvicorn

    from dustbunny.server import serve

    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    monkeypatch.setenv("DUSTBUNNY_COMMIT", "e722bb5fd445f8f6c1dbd40e30879f5e3a8e1c92")
    settings = Settings(scan_roots=[str(tmp_path)], data_dir=tmp_path, docker_enabled=False)
    with caplog.at_level("INFO", logger="dustbunny.server"):
        serve(settings)
    assert f"Dustbunny {__version__} (commit e722bb5)" in caplog.text
