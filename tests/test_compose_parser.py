from __future__ import annotations

from pathlib import Path

from dustbunny.compose_parser import find_compose_files, load_compose_file, parse_compose
from dustbunny.models import RefState


def by_kind(result, kind: str) -> set[str]:
    return {r.path for r in result.references if r.kind == kind}


def test_short_syntax(compose_text) -> None:
    result = parse_compose(compose_text("short_syntax.yml"), base_dir="/opt/stacks/sonarr")
    assert by_kind(result, "bind") == {
        "/opt/appdata/sonarr",
        "/mnt/media/tv",
        "/opt/stacks/sonarr/local",
        "/opt/appdata/quoted",
        "/opt/appdata/trailing",
    }
    # Anonymous volume and named volume are not binds.
    assert "/var/lib/anonymous" not in by_kind(result, "bind")
    assert all(r.state is RefState.DEFINED for r in result.references)


def test_short_syntax_relative_paths_skipped_without_base_dir(compose_text) -> None:
    result = parse_compose(compose_text("short_syntax.yml"))
    assert "/opt/stacks/sonarr/local" not in by_kind(result, "bind")
    assert any("./local" in w for w in result.warnings)


def test_long_syntax(compose_text) -> None:
    result = parse_compose(compose_text("long_syntax.yml"), base_dir="/opt/stacks/app")
    assert by_kind(result, "bind") == {
        "/opt/appdata/app/config",
        "/opt/stacks/app/relative-data",
    }


def test_named_volume_device(compose_text) -> None:
    result = parse_compose(compose_text("named_volume_device.yml"), owner="nextcloud")
    assert by_kind(result, "volume-device") == {"/opt/appdata/nextcloud/data"}
    ref = next(r for r in result.references if r.kind == "volume-device")
    assert ref.owner == "nextcloud"
    assert "volume nc_data" in (ref.origin or "")


def test_env_substitution(compose_text) -> None:
    env = {"APPDATA": "/opt/appdata", "ROOT": "/srv/root"}
    result = parse_compose(compose_text("env_substitution.yml"), env=env)
    binds = {r.path: r for r in result.references if r.kind == "bind"}
    assert "/opt/appdata/radarr" in binds
    assert "/opt/appdata/prowlarr" in binds  # default used
    assert "/srv/conf/bazarr" in binds  # default used
    assert "/srv/root/plex" in binds

    lidarr = binds["${UNKNOWN}/lidarr"]
    assert lidarr.glob == "*/lidarr"
    readarr = binds["${MISSING:?must be set}/readarr"]
    assert readarr.glob == "*/readarr"
    # A lone unresolved variable may be a volume name: not a path, but warned about.
    assert not any(r.path == "${VOLUME_NAME}" for r in result.references)
    assert any("VOLUME_NAME" in w for w in result.warnings)
    # $$ escapes must not turn into references or unresolved markers.
    assert not any("NOT_A_VAR" in r.path for r in result.references)


def test_env_substitution_from_portainer_style_env(compose_text) -> None:
    # Portainer passes stack.Env as name/value pairs; it's just a mapping here.
    result = parse_compose(
        compose_text("env_substitution.yml"),
        env={"APPDATA": "/data/apps", "UNKNOWN": "/x", "MISSING": "/y", "ROOT": "/r"},
    )
    assert {"/data/apps/radarr", "/x/lidarr", "/y/readarr"} <= by_kind(result, "bind")
    assert not any(r.glob for r in result.references)


def test_extras(compose_text) -> None:
    result = parse_compose(compose_text("extras.yml"), base_dir="/opt/stacks/extras")
    assert result.project == "extras-project"
    assert all(r.owner == "extras-project" for r in result.references)
    assert by_kind(result, "env-file") == {
        "/opt/stacks/extras/common.env",
        "/opt/appdata/web/web.env",
        "/opt/stacks/shared/.env",
    }
    assert by_kind(result, "build-context") == {"/opt/stacks/extras/build"}
    assert by_kind(result, "extends") == {"/opt/stacks/extras/base.yml"}
    assert by_kind(result, "include") == {
        "/opt/stacks/extras/other/compose.yaml",
        "/opt/stacks/shared/compose.yaml",
    }
    assert by_kind(result, "config") == {"/opt/appdata/nginx/nginx.conf"}
    assert by_kind(result, "secret") == {"/opt/stacks/extras/secrets/db_password.txt"}


def test_broken_yaml_falls_back_to_raw_text(compose_text) -> None:
    result = parse_compose(compose_text("broken.yml"))
    assert "/opt/appdata/broken" in by_kind(result, "raw-text")
    assert any("YAML could not be parsed" in w for w in result.warnings)


def test_raw_text_safety_net(compose_text) -> None:
    result = parse_compose(compose_text("commented.yml"))
    raw = by_kind(result, "raw-text")
    assert "/opt/appdata/old-app" in raw  # commented out, still protected
    assert "/opt/appdata/app-extra" in raw  # only mentioned in an env var
    assert "/opt/appdata/app" not in raw  # already a structured bind, no duplicate
    assert not any("not-a-path" in p for p in raw)  # URL path is glued to the host


def test_raw_text_does_not_split_unresolved_variables(compose_text) -> None:
    result = parse_compose(compose_text("env_substitution.yml"))
    raw = by_kind(result, "raw-text")
    assert "/lidarr" not in raw
    assert "/readarr" not in raw


def test_non_mapping_document() -> None:
    result = parse_compose("- just\n- a list /opt/appdata/x\n")
    assert by_kind(result, "raw-text") == {"/opt/appdata/x"}
    assert result.warnings


def test_home_directory_is_unresolved() -> None:
    result = parse_compose("services:\n  a:\n    volumes:\n      - ~/appdata/a:/config\n")
    ref = next(r for r in result.references if r.kind == "bind")
    assert ref.path == "~/appdata/a"
    assert ref.glob == "*/appdata/a"


def test_load_compose_file_reads_dotenv(tmp_path: Path) -> None:
    stack = tmp_path / "mystack"
    stack.mkdir()
    (stack / ".env").write_text("APPDATA=/opt/appdata\n")
    (stack / "compose.yaml").write_text(
        "services:\n  a:\n    volumes:\n      - ${APPDATA}/a:/config\n      - ./data:/data\n"
    )
    result = load_compose_file(stack / "compose.yaml", state=RefState.STOPPED)
    assert by_kind(result, "bind") == {"/opt/appdata/a", f"{stack}/data"}
    assert by_kind(result, "project-dir") == {str(stack)}
    assert all(r.owner == "mystack" for r in result.references)
    assert all(r.state is RefState.STOPPED for r in result.references)


def test_find_compose_files(tmp_path: Path) -> None:
    for name in ("compose.yaml", "compose.override.yaml", "docker-compose.yml", "other.yml"):
        (tmp_path / name).write_text("services: {}\n")
    names = [p.name for p in find_compose_files(tmp_path)]
    assert names == ["compose.yaml", "compose.override.yaml", "docker-compose.yml"]
