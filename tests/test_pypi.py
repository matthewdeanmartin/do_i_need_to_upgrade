"""Tests for the pypi module (mocked network)."""

from __future__ import annotations


import pytest

from do_i_need_to_upgrade.pypi import (
    PypiError,
    parse_version_detail,
    validate_name,
    validate_pypi_url,
)


def test_validate_name_ok() -> None:
    """Valid names pass."""
    assert validate_name("my-pkg") == "my-pkg"


def test_validate_name_bad_empty() -> None:
    """Empty name raises PypiError."""
    with pytest.raises(PypiError):
        validate_name("")


def test_validate_name_bad_leading_dash() -> None:
    """Name starting with dash raises PypiError."""
    with pytest.raises(PypiError):
        validate_name("-badname")


def test_validate_pypi_url_ok() -> None:
    """Valid pypi.org URLs pass."""
    url = "https://pypi.org/pypi/my-pkg/json"
    assert validate_pypi_url(url) == url


def test_validate_pypi_url_http() -> None:
    """HTTP (not HTTPS) raises PypiError."""
    with pytest.raises(PypiError):
        validate_pypi_url("http://pypi.org/pypi/pkg/json")


def test_validate_pypi_url_bad_domain() -> None:
    """Non-pypi.org URLs raise PypiError."""
    with pytest.raises(PypiError):
        validate_pypi_url("https://evil.com/package")


_SAMPLE_PAYLOAD = {
    "info": {"version": "2.0.0"},
    "releases": {
        "1.0.0": [{"upload_time_iso_8601": "2024-01-01T00:00:00Z", "yanked": False}],
        "2.0.0": [{"upload_time_iso_8601": "2025-01-01T00:00:00Z", "yanked": False}],
        "1.5.0b1": [{"upload_time_iso_8601": "2024-06-01T00:00:00Z", "yanked": False}],
    },
}


def test_parse_version_detail_stable() -> None:
    """Stable latest is extracted correctly."""
    detail = parse_version_detail(_SAMPLE_PAYLOAD, current_version="1.0.0")
    assert detail.latest == "2.0.0"
    assert detail.latest_stable == "2.0.0"
    assert not detail.is_prerelease
    assert not detail.is_yanked
    assert not detail.is_dev


def test_parse_version_detail_published() -> None:
    """Publish date is extracted."""
    detail = parse_version_detail(_SAMPLE_PAYLOAD, current_version="1.0.0")
    assert detail.published is not None
    assert detail.published.tzinfo is not None


def test_parse_version_detail_yanked_current() -> None:
    """Yanked current version is flagged."""
    payload = {
        "info": {"version": "2.0.0"},
        "releases": {
            "1.0.0": [{"yanked": True}],
            "2.0.0": [{"yanked": False}],
        },
    }
    detail = parse_version_detail(payload, current_version="1.0.0")
    assert detail.is_yanked


def test_parse_version_detail_skip_yanked_latest() -> None:
    """Yanked versions are not considered as upgrade candidates."""
    payload = {
        "info": {"version": "3.0.0"},
        "releases": {
            "1.0.0": [{"yanked": False}],
            "2.0.0": [{"yanked": False}],
            "3.0.0": [{"yanked": True}],  # yanked, should be excluded
        },
    }
    detail = parse_version_detail(payload, current_version="1.0.0")
    assert detail.latest == "2.0.0"


def test_parse_version_detail_missing_info_version() -> None:
    """Missing info.version raises PypiError."""
    payload = {"info": {}, "releases": {}}
    with pytest.raises(PypiError):
        parse_version_detail(payload, current_version="1.0.0")
