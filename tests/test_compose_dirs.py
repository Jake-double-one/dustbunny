from __future__ import annotations

from pathlib import Path

from dustbunny.collectors.compose_files import ComposeDirsCollector


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_compose_dirs(tmp_path: Path) -> None:
    stacks = tmp_path / "stacks"
    write(stacks / "media" / "compose.yaml", "services:\n  a:\n    volumes:\n      - ./config:/c\n")
    write(stacks / "media" / ".env", "X=1\n")
    write(
        stacks / "wiki" / "docker-compose.yml",
        "services:\n  w:\n    volumes:\n      - /opt/appdata/wiki:/w\n",
    )
    write(stacks / "notes.txt", "not a stack")
    write(stacks / "deep" / "nested" / "compose.yaml", "services: {}\n")  # too deep, skipped
    result = ComposeDirsCollector([stacks]).collect()
    binds = {(r.path, r.owner) for r in result.references if r.kind == "bind"}
    assert binds == {(f"{stacks}/media/config", "media"), ("/opt/appdata/wiki", "wiki")}
    assert {r.path for r in result.references if r.kind == "project-dir"} == {
        f"{stacks}/media",
        f"{stacks}/wiki",
    }
    assert result.error is None


def test_missing_dir_is_an_error(tmp_path: Path) -> None:
    result = ComposeDirsCollector([tmp_path / "nope"]).collect()
    assert result.error is not None and "nope" in result.error
