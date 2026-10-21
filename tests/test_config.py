from __future__ import annotations

from datetime import timedelta

import pytest

from dustbunny.config import Settings, parse_duration


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("90", timedelta(seconds=90)),
        ("30m", timedelta(minutes=30)),
        ("6h", timedelta(hours=6)),
        ("1d12h", timedelta(days=1, hours=12)),
        (3600, timedelta(hours=1)),
    ],
)
def test_parse_duration(raw, expected) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["", "soon", "5x", "-1h"])
def test_parse_duration_rejects(raw) -> None:
    with pytest.raises(ValueError):
        parse_duration(raw)


def test_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("SCAN_ROOTS", "/opt/appdata, /srv/appdata")
    monkeypatch.setenv("IGNORE", "backup-*,*.old")
    monkeypatch.setenv("SCAN_INTERVAL", "12h")
    monkeypatch.setenv("PORTAINER_URL", "https://portainer:9443")
    monkeypatch.setenv("PORTAINER_API_KEY", "ptr_secret")
    monkeypatch.setenv("PORTAINER_ENDPOINT_ID", "")
    settings = Settings()
    assert settings.scan_roots == ["/opt/appdata", "/srv/appdata"]
    assert settings.ignore == ["backup-*", "*.old"]
    assert settings.scan_interval == timedelta(hours=12)
    assert settings.portainer_api_key is not None
    assert "ptr_secret" not in repr(settings)
    assert settings.portainer_enabled
    assert settings.portainer_endpoint_id is None


@pytest.mark.parametrize(
    "env",
    [
        {"AUTH_USER": "admin"},
        {"AUTH_PASSWORD": "secret"},
        {"PORTAINER_URL": "https://p:9443"},
        {"PORTAINER_API_KEY": "ptr_x"},
    ],
)
def test_half_configured_pairs_are_errors(monkeypatch, env) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="both"):
        Settings()
