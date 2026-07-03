"""Tests for installed module."""

from __future__ import annotations

from do_i_need_to_upgrade.installed import host_version, parse_requirement_name


def test_parse_simple() -> None:
    """Simple package name is parsed."""
    assert parse_requirement_name("requests") == "requests"


def test_parse_with_specifier() -> None:
    """Name with specifier strips the specifier."""
    assert parse_requirement_name("requests>=2.0") == "requests"


def test_parse_with_extras() -> None:
    """Extras are stripped."""
    assert parse_requirement_name("requests[security]>=2.0") == "requests"


def test_parse_with_marker() -> None:
    """Marker is stripped."""
    result = parse_requirement_name('requests; python_version >= "3.8"')
    assert result == "requests"


def test_parse_empty() -> None:
    """Empty string returns None."""
    assert parse_requirement_name("") is None


def test_host_version_self() -> None:
    """packaging is installed and has a version."""
    result = host_version("packaging")
    assert result is not None
    assert isinstance(result, str)


def test_host_version_missing() -> None:
    """Non-existent package returns None."""
    result = host_version("__nonexistent_package_xyz_abc__")
    assert result is None
