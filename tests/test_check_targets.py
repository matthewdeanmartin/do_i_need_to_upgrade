"""Tests for api.check_targets and the target-checking CLI paths."""

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

from do_i_need_to_upgrade import api, cli, resolvers
from do_i_need_to_upgrade.cache import Cache, utcnow
from do_i_need_to_upgrade.host import GenericHost
from do_i_need_to_upgrade.install_method import InstallMethod
from do_i_need_to_upgrade.resolvers import Target


def _seed_cache(cache_dir: Path, name: str, latest: str) -> None:
    cache = Cache.load(cache_dir)
    # Published well in the past so the 14-day cooloff window does not apply.
    cache.put_package(name, latest, utcnow() - timedelta(days=30))
    cache.save()


def test_check_targets_upgrade_available() -> None:
    """An installed target older than cached latest is an upgrade."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "ruff", "9.9.9")
        host = GenericHost(dist_name="unused", cache_dir=cache_dir)
        targets = [Target("ruff", "0.1.0", InstallMethod.UV_TOOL, "uv-tool")]
        report = api.check_targets(targets, host=host, allow_network=False)
        assert len(report.dependencies) == 1
        info = report.dependencies[0]
        assert info.is_upgrade_available
        assert info.latest == "9.9.9"


def test_check_targets_up_to_date() -> None:
    """A target at the latest version is not an upgrade."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "ruff", "1.0.0")
        host = GenericHost(dist_name="unused", cache_dir=cache_dir)
        targets = [Target("ruff", "1.0.0", InstallMethod.PIPX, "pipx")]
        report = api.check_targets(targets, host=host, allow_network=False)
        assert not report.dependencies[0].is_upgrade_available


def test_check_targets_not_installed() -> None:
    """A not-installed target yields a note with the latest version."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "some-tool", "2.0.0")
        host = GenericHost(dist_name="unused", cache_dir=cache_dir)
        targets = [Target("some-tool", None, InstallMethod.UNKNOWN, "none")]
        report = api.check_targets(targets, host=host, allow_network=False)
        assert report.dependencies[0].installed == "(not installed)"
        assert not report.dependencies[0].is_upgrade_available
        assert any("not installed" in note and "2.0.0" in note for note in report.notes)


def test_cli_check_targets_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI check with a positional target exits 10 when an upgrade exists."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "ruff", "9.9.9")
        monkeypatch.setattr(
            resolvers, "resolve_all", lambda names: [Target("ruff", "0.1.0", InstallMethod.UV_TOOL, "uv-tool")]
        )
        rc = cli.main(["--cache-dir", str(cache_dir), "--no-network", "check", "ruff"])
        assert rc == cli.EXIT_UPGRADES_AVAILABLE
        out = capsys.readouterr().out
        assert "ruff" in out


def test_cli_check_quiet_prints_nothing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """--quiet suppresses output but keeps the exit code."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "ruff", "9.9.9")
        monkeypatch.setattr(
            resolvers, "resolve_all", lambda names: [Target("ruff", "0.1.0", InstallMethod.UV_TOOL, "uv-tool")]
        )
        rc = cli.main(["--cache-dir", str(cache_dir), "--no-network", "--quiet", "check", "ruff"])
        assert rc == cli.EXIT_UPGRADES_AVAILABLE
        assert capsys.readouterr().out == ""


def test_cli_watch_roundtrip(capsys: pytest.CaptureFixture[str]) -> None:
    """watch add / list / remove round-trips through the CLI."""
    with tempfile.TemporaryDirectory() as d:
        assert cli.main(["--cache-dir", d, "watch", "add", "ruff", "black"]) == 0
        capsys.readouterr()
        assert cli.main(["--cache-dir", d, "watch", "list"]) == 0
        out = capsys.readouterr().out
        assert "ruff" in out and "black" in out
        assert cli.main(["--cache-dir", d, "watch", "remove", "ruff"]) == 0
        capsys.readouterr()
        assert cli.main(["--cache-dir", d, "watch", "list"]) == 0
        out = capsys.readouterr().out
        assert "ruff" not in out and "black" in out


def test_cli_check_watched(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """check --watched pulls names from the persisted watch list."""
    with tempfile.TemporaryDirectory() as d:
        cache_dir = Path(d)
        _seed_cache(cache_dir, "ruff", "1.0.0")
        cache = Cache.load(cache_dir)
        cache.watch_add("ruff")
        cache.save()
        seen: list[str] = []

        def fake_resolve_all(names: list[str]) -> list[Target]:
            seen.extend(names)
            return [Target("ruff", "1.0.0", InstallMethod.PIPX, "pipx")]

        monkeypatch.setattr(resolvers, "resolve_all", fake_resolve_all)
        rc = cli.main(["--cache-dir", str(cache_dir), "--no-network", "check", "--watched"])
        assert rc == 0
        assert seen == ["ruff"]


def test_cli_upgrade_unknown_target(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Upgrading an unresolvable target fails with a clear message."""
    monkeypatch.setattr(resolvers, "resolve", lambda name: Target(name, None, InstallMethod.UNKNOWN, "none"))
    with tempfile.TemporaryDirectory() as d:
        rc = cli.main(["--cache-dir", d, "upgrade", "nonexistent-tool"])
    assert rc == cli.EXIT_ERROR
    assert "Cannot upgrade" in capsys.readouterr().err


def test_cli_snooze_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """snooze --dry-run parses but does not create the cache file."""
    with tempfile.TemporaryDirectory() as d:
        rc = cli.main(["--cache-dir", d, "snooze", "pkg==1.0", "--days", "3", "--dry-run"])
        assert rc == 0
        assert "Would snooze" in capsys.readouterr().out
        assert not (Path(d) / "do_i_need_to_upgrade.json").exists()


def test_cli_watch_add_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    """watch add --dry-run reports but does not persist."""
    with tempfile.TemporaryDirectory() as d:
        assert cli.main(["--cache-dir", d, "watch", "add", "--dry-run", "pkg"]) == 0
        assert "Would watch" in capsys.readouterr().out
        assert Cache.load(Path(d)).watch_list() == []


def test_cli_clear_cache_dry_run_keeps_data(capsys: pytest.CaptureFixture[str]) -> None:
    """clear-cache --dry-run leaves cache contents intact."""
    with tempfile.TemporaryDirectory() as d:
        assert cli.main(["--cache-dir", d, "snooze", "pkg==1.0"]) == 0
        capsys.readouterr()
        assert cli.main(["--cache-dir", d, "clear-cache", "--dry-run"]) == 0
        assert "Would clear" in capsys.readouterr().out
        assert Cache.load(Path(d)).is_snoozed("pkg==1.0")
