"""Tests for the Settings configuration layer."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from do_i_need_to_upgrade.settings import ENV_VAR, Settings, user_config_path


@pytest.fixture(autouse=True)
def _isolate_user_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point env-var and user-config lookups away from the real machine."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


def test_defaults() -> None:
    """Default Settings match the documented behavior."""
    settings = Settings(dist_name="my-app")
    assert settings.position == "start"
    assert settings.allow_network
    assert settings.check_dependencies
    assert settings.notify == "return-only"
    assert settings.check_ttl == timedelta(hours=24)
    assert settings.cooloff == timedelta(days=14)


def test_to_host_defaults_cache_dir() -> None:
    """to_host fills in the per-user cache dir."""
    host = Settings(dist_name="my-app").to_host()
    assert host.dist_name == "my-app"
    assert "do_i_need_to_upgrade-my-app" in str(host.cache_dir)


def test_from_table() -> None:
    """Recognized table keys map onto Settings fields."""
    settings = Settings.from_table(
        {
            "position": "end",
            "notify": "exit-message",
            "cooloff_days": 7,
            "check_ttl_hours": 6,
            "check_dependencies": False,
            "include_prereleases": True,
        },
        dist_name="my-app",
    )
    assert settings.position == "end"
    assert settings.notify == "exit-message"
    assert settings.cooloff == timedelta(days=7)
    assert settings.check_ttl == timedelta(hours=6)
    assert not settings.check_dependencies
    assert settings.include_prereleases


def test_from_table_ignores_invalid() -> None:
    """Invalid values fall back to defaults instead of raising."""
    settings = Settings.from_table(
        {"position": "sideways", "cooloff_days": -1, "check_ttl_hours": True, "index_url": "http://insecure/{name}"},
        dist_name="my-app",
    )
    assert settings.position == "start"
    assert settings.cooloff == timedelta(days=14)
    assert settings.check_ttl == timedelta(hours=24)
    assert settings.index_url.startswith("https://pypi.org")


def test_from_table_enabled_false() -> None:
    """enabled = false forces position off."""
    settings = Settings.from_table({"enabled": False}, dist_name="my-app")
    assert settings.position == "off"


def test_from_toml_pyproject_table(tmp_path: Path) -> None:
    """from_toml reads the [tool.do_i_need_to_upgrade] table."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.do_i_need_to_upgrade]\nposition = "both"\ncooloff_days = 3\n',
        encoding="utf-8",
    )
    settings = Settings.from_toml(pyproject, dist_name="my-app")
    assert settings.position == "both"
    assert settings.cooloff == timedelta(days=3)


def test_from_pyproject_walks_up(tmp_path: Path) -> None:
    """from_pyproject finds pyproject.toml in an ancestor directory."""
    (tmp_path / "pyproject.toml").write_text('[tool.do_i_need_to_upgrade]\nnotify = "exit-message"\n', encoding="utf-8")
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    settings = Settings.from_pyproject("my-app", start=nested)
    assert settings.notify == "exit-message"


def test_from_pyproject_missing(tmp_path: Path) -> None:
    """No pyproject.toml anywhere yields plain defaults."""
    settings = Settings.from_pyproject("my-app", start=tmp_path)
    assert settings == Settings(dist_name="my-app")


def test_resolve_env_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """DO_I_NEED_TO_UPGRADE=off disables checking."""
    monkeypatch.setenv(ENV_VAR, "off")
    assert Settings(dist_name="my-app").resolve().position == "off"


def test_resolve_env_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """DO_I_NEED_TO_UPGRADE=no-network keeps checks but blocks fetches."""
    monkeypatch.setenv(ENV_VAR, "no-network")
    resolved = Settings(dist_name="my-app").resolve()
    assert resolved.position == "start"
    assert not resolved.allow_network


def test_resolve_user_config_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The user config file can disable checking globally."""
    config = user_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("disabled = true\n", encoding="utf-8")
    assert Settings(dist_name="my-app").resolve().position == "off"


def test_resolve_user_config_disabled_for(tmp_path: Path) -> None:
    """disabled_for only affects the listed distributions."""
    config = user_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('disabled_for = ["noisy-app"]\n', encoding="utf-8")
    assert Settings(dist_name="noisy-app").resolve().position == "off"
    assert Settings(dist_name="other-app").resolve().position == "start"


def test_resolve_env_beats_user_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variable wins over the user config file."""
    config = user_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("no_network = true\n", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, "off")
    resolved = Settings(dist_name="my-app").resolve()
    assert resolved.position == "off"
    assert not resolved.allow_network
