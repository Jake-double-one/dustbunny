from __future__ import annotations

import json
from pathlib import Path

import pytest

from dustbunny.cli import main


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    for name in ("SCAN_ROOTS", "IGNORE", "PATH_ALIASES", "SCAN_SIZES"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "appdata"
    for name in ("sonarr", "radarr", "old-app", "lost+found"):
        (root / name).mkdir(parents=True)
    (root / "old-app" / "big.db").write_bytes(b"z" * 4096)

    stack = tmp_path / "stacks" / "media"
    stack.mkdir(parents=True)
    (stack / ".env").write_text(f"APPDATA={root}\n")
    (stack / "compose.yaml").write_text(
        "services:\n  sonarr:\n    volumes:\n      - ${APPDATA}/sonarr:/config\n"
    )
    refs = tmp_path / "refs.json"
    refs.write_text(json.dumps([{"path": f"{root}/radarr/config", "state": "running"}]))
    return {"root": root, "compose": stack / "compose.yaml", "refs": refs, "tmp": tmp_path}


def run_json(capsys: pytest.CaptureFixture[str], *args: str) -> dict:
    assert main(["--once", "--json", *args]) == 0
    return json.loads(capsys.readouterr().out)


def test_once_json(setup, capsys) -> None:
    report = run_json(
        capsys,
        "--root", str(setup["root"]),
        "--compose", str(setup["compose"]),
        "--references", str(setup["refs"]),
    )  # fmt: skip
    categories = {f["name"]: f["category"] for f in report["folders"]}
    assert categories == {
        "old-app": "orphan",
        "sonarr": "defined-only",
        "radarr": "active",
        "lost+found": "ignored",
    }
    assert report["complete"] is True
    assert [s["name"] for s in report["sources"]] == ["static", "compose-files"]
    orphan = report["folders"][0]
    assert orphan["size_bytes"] >= 4096
    assert orphan["checked_sources"] == ["static", "compose-files"]
    assert report["summary"]["counts"]["orphan"] == 1


def test_roots_and_ignore_from_env(setup, capsys, monkeypatch) -> None:
    monkeypatch.setenv("SCAN_ROOTS", f"{setup['root']}, /nonexistent")
    monkeypatch.setenv("IGNORE", "old-*")
    report = run_json(capsys, "--references", str(setup["refs"]), "--no-size")
    categories = {f["name"]: f["category"] for f in report["folders"]}
    assert categories["old-app"] == "ignored"
    assert all(f["size_bytes"] is None for f in report["folders"])
    assert any(w["params"].get("root") == "/nonexistent" for w in report["warnings"])


def test_text_output_and_output_file(setup, capsys) -> None:
    out = setup["tmp"] / "report.txt"
    assert main(["--once", "--root", str(setup["root"]), "-o", str(out)]) == 0
    text = out.read_text()
    assert "orphan" in text
    assert "incomplete result" in text  # no sources configured


def test_without_once_starts_the_server(monkeypatch) -> None:
    started = []
    monkeypatch.setattr("dustbunny.server.serve", lambda settings: started.append(settings))
    assert main([]) == 0
    assert len(started) == 1


def test_missing_roots_is_an_error(capsys, monkeypatch) -> None:
    monkeypatch.delenv("SCAN_ROOTS", raising=False)
    assert main(["--once"]) == 2
    assert "SCAN_ROOTS" in capsys.readouterr().err
