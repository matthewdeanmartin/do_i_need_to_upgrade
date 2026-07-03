"""Tests for the host module."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from do_i_need_to_upgrade.host import GenericHost, Host, default_host


def test_generic_host_attrs() -> None:
    """GenericHost exposes all Host protocol attributes."""
    with tempfile.TemporaryDirectory() as d:
        host = GenericHost(dist_name="my-app", cache_dir=Path(d))
        assert host.dist_name == "my-app"
        assert host.cache_dir == Path(d)
        assert isinstance(host.logger, logging.Logger)


def test_host_protocol_satisfied() -> None:
    """GenericHost satisfies Host protocol."""
    with tempfile.TemporaryDirectory() as d:
        host = GenericHost(dist_name="x", cache_dir=Path(d))
        assert isinstance(host, Host)


def test_default_host() -> None:
    """default_host returns a Host instance."""
    host = default_host("some-app")
    assert isinstance(host, Host)
    assert host.dist_name == "some-app"


def test_default_host_default_name() -> None:
    """default_host uses 'do_i_need_to_upgrade' when no name given."""
    host = default_host()
    assert host.dist_name == "do_i_need_to_upgrade"


def test_generic_host_default_cache_dir() -> None:
    """GenericHost defaults cache_dir to a per-user cache path."""
    host = GenericHost(dist_name="app")
    assert "do_i_need_to_upgrade-app" in str(host.cache_dir)
