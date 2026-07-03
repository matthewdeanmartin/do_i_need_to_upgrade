"""Tests for the argparse drop-in integration helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from do_i_need_to_upgrade import integrate
from do_i_need_to_upgrade.settings import ENV_VAR, Settings


@pytest.fixture(autouse=True)
def _isolate_user_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point env-var and user-config lookups away from the real machine."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))


def _toy_app_parser(settings: Settings) -> argparse.ArgumentParser:
    """Build a host-app-shaped parser with our commands integrated."""
    parser = argparse.ArgumentParser(prog="my-app")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    own = subparsers.add_parser("frobnicate")
    own.add_argument("--dry-run", action="store_true")  # host's own dry-run must not collide
    integrate.add_upgrade_command(subparsers, "do_i_need_to_upgrade", settings=settings)
    integrate.add_check_command(subparsers, "do_i_need_to_upgrade", settings=settings)
    return parser


def _settings(tmp_path: Path) -> Settings:
    return Settings(dist_name="do_i_need_to_upgrade", cache_dir=tmp_path / "cache", allow_network=False)


def test_non_integrated_command_returns_none(tmp_path: Path) -> None:
    """The host's own subcommands are not intercepted."""
    parser = _toy_app_parser(_settings(tmp_path))
    args = parser.parse_args(["frobnicate", "--dry-run"])
    assert integrate.run_if_upgrade_command(args) is None


def test_upgrade_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """upgrade --dry-run dispatches and returns an exit code."""
    parser = _toy_app_parser(_settings(tmp_path))
    args = parser.parse_args(["upgrade", "--dry-run"])
    rc = integrate.run_if_upgrade_command(args)
    # Editable dev install has no upgrade path (rc 1); normal installs print the argv (rc 0).
    assert rc in (0, 1)
    captured = capsys.readouterr()
    assert (captured.out + captured.err).strip()


def test_upgrade_check_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """upgrade --check reports without installing."""
    parser = _toy_app_parser(_settings(tmp_path))
    args = parser.parse_args(["upgrade", "--check"])
    rc = integrate.run_if_upgrade_command(args)
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_check_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """check-updates runs cache-only and exits 0 with an empty cache."""
    parser = _toy_app_parser(_settings(tmp_path))
    args = parser.parse_args(["check-updates", "--no-network"])
    rc = integrate.run_if_upgrade_command(args)
    assert rc == 0
    assert "up to date" in capsys.readouterr().out


def test_install_background_check(tmp_path: Path) -> None:
    """The one-liner returns a Report when enabled."""
    report = integrate.install_background_check("do_i_need_to_upgrade", settings=_settings(tmp_path))
    assert report is not None
    assert report.host_dist is not None


def test_install_background_check_kill_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DO_I_NEED_TO_UPGRADE=off disables the background check entirely."""
    monkeypatch.setenv(ENV_VAR, "off")
    report = integrate.install_background_check("do_i_need_to_upgrade", settings=_settings(tmp_path))
    assert report is None


def test_custom_command_name(tmp_path: Path) -> None:
    """The subcommand name is configurable."""
    parser = argparse.ArgumentParser(prog="my-app")
    subparsers = parser.add_subparsers(dest="command")
    integrate.add_upgrade_command(
        subparsers, "do_i_need_to_upgrade", command="self-update", settings=_settings(tmp_path)
    )
    args = parser.parse_args(["self-update", "--check"])
    assert integrate.run_if_upgrade_command(args) == 0
