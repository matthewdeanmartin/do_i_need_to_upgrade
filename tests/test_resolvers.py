"""Tests for the resolvers module (no real subprocesses or network)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from do_i_need_to_upgrade import installed, resolvers
from do_i_need_to_upgrade.install_method import InstallMethod
from do_i_need_to_upgrade.resolvers import (
    Target,
    _parse_pipx_list,
    _parse_uv_tool_list,
    parse_requirements_file,
    resolve,
    resolve_all,
)


@pytest.fixture(autouse=True)
def _clear_listing_caches() -> None:
    """Reset per-process tool-listing caches between tests."""
    resolvers.uv_tool_versions.cache_clear()
    resolvers.pipx_versions.cache_clear()


def test_parse_uv_tool_list() -> None:
    """uv tool list output parses into name->version."""
    text = "ruff v0.4.4\n- ruff\nblack v24.4.2\n- black\n- blackd\n"
    assert _parse_uv_tool_list(text) == {"ruff": "0.4.4", "black": "24.4.2"}


def test_parse_uv_tool_list_ignores_garbage() -> None:
    """Unrecognized lines are skipped."""
    assert not _parse_uv_tool_list("warning: something\n")


def test_parse_pipx_list() -> None:
    """pipx list --json output parses into name->version."""
    text = (
        '{"pipx_spec_version": "0.1", "venvs": {"yt-dlp": {"metadata": '
        '{"main_package": {"package": "yt-dlp", "package_version": "2024.1.1"}}}}}'
    )
    assert _parse_pipx_list(text) == {"yt-dlp": "2024.1.1"}


def test_parse_pipx_list_bad_json() -> None:
    """Invalid JSON yields an empty mapping."""
    assert not _parse_pipx_list("not json")


def test_resolve_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dist in the current environment resolves with source 'env'."""
    target = resolve("packaging")
    assert target.source == "env"
    assert target.installed_version is not None


def test_resolve_uv_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """A uv-managed tool resolves with UV_TOOL method."""
    monkeypatch.setattr(installed, "host_version", lambda name: None)
    monkeypatch.setattr(resolvers, "uv_tool_versions", lambda: {"ruff": "0.4.4"})
    monkeypatch.setattr(resolvers, "pipx_versions", lambda: {})
    target = resolve("ruff")
    assert target == Target("ruff", "0.4.4", InstallMethod.UV_TOOL, "uv-tool")


def test_resolve_pipx_normalized_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """pipx lookup tolerates -/_ differences."""
    monkeypatch.setattr(installed, "host_version", lambda name: None)
    monkeypatch.setattr(resolvers, "uv_tool_versions", lambda: {})
    monkeypatch.setattr(resolvers, "pipx_versions", lambda: {"yt-dlp": "2024.1.1"})
    target = resolve("yt_dlp")
    assert target.installed_version == "2024.1.1"
    assert target.install_method == InstallMethod.PIPX


def test_resolve_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing found anywhere yields source 'none' and no version."""
    monkeypatch.setattr(installed, "host_version", lambda name: None)
    monkeypatch.setattr(resolvers, "uv_tool_versions", lambda: {})
    monkeypatch.setattr(resolvers, "pipx_versions", lambda: {})
    monkeypatch.setattr(shutil, "which", lambda name: None)
    target = resolve("definitely-not-a-real-package-xyz")
    assert target.source == "none"
    assert target.installed_version is None


def test_resolve_all_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_all drops duplicate names, tolerating -/_ and case."""
    monkeypatch.setattr(resolvers, "resolve", lambda name: Target(name, "1.0", InstallMethod.UNKNOWN, "env"))
    targets = resolve_all(["My-Pkg", "my_pkg", "other"])
    assert [t.name for t in targets] == ["My-Pkg", "other"]


def test_parse_requirements_file(tmp_path: Path) -> None:
    """Names are extracted; comments, options, and junk are skipped."""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# a comment\n"
        "requests==2.31.0\n"
        "packaging>=23.0  # inline comment\n"
        "-e ./local\n"
        "--index-url https://example.invalid/simple\n"
        "flask[async]>=3.0; python_version >= '3.10'\n"
        "requests\n",
        encoding="utf-8",
    )
    assert parse_requirements_file(req) == ["requests", "packaging", "flask"]
