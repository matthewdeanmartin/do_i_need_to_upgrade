"""Host adapter protocol for do_i_need_to_upgrade.

The Host protocol is the only coupling point between this library and a host
application. Implement it (or use GenericHost) to integrate with any app.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable


def user_cache_dir(dist_name: str) -> Path:
    """Return a per-user cache directory for dist_name.

    Uses the platform-conventional user cache location rather than the
    system tempdir: tempdirs are world-shared (predictable-path risk on
    multi-user systems) and are wiped on reboot, which defeats caching.

    Args:
        dist_name: The distribution name the cache belongs to.

    Returns:
        Path to a per-user cache directory (not created).
    """
    leaf = f"do_i_need_to_upgrade-{dist_name}"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / leaf / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / leaf
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / leaf


@runtime_checkable
class Host(Protocol):
    """Minimal protocol a host application must satisfy."""

    @property
    def dist_name(self) -> str:
        """Name of the distribution this host represents (e.g. 'my-app')."""
        raise NotImplementedError

    @property
    def cache_dir(self) -> Path:
        """Directory where do_i_need_to_upgrade may write its sidecar cache."""
        raise NotImplementedError

    @property
    def logger(self) -> logging.Logger:
        """Logger used by do_i_need_to_upgrade."""
        raise NotImplementedError


class GenericHost:
    """Stdlib-only host for standalone or embedded use."""

    def __init__(
        self,
        dist_name: str,
        cache_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialise a GenericHost.

        Args:
            dist_name: PyPI distribution name.
            cache_dir: Where to store the cache. Defaults to the per-user
                cache directory from user_cache_dir().
            logger: Logger instance. Defaults to logging.getLogger(dist_name).
        """
        self._dist_name = dist_name
        self._cache_dir = cache_dir or user_cache_dir(dist_name)
        self._logger = logger or logging.getLogger(f"do_i_need_to_upgrade.{dist_name}")

    @property
    def dist_name(self) -> str:
        """Name of the distribution this host represents."""
        return self._dist_name

    @property
    def cache_dir(self) -> Path:
        """Directory where do_i_need_to_upgrade writes its sidecar cache."""
        return self._cache_dir

    @property
    def logger(self) -> logging.Logger:
        """Logger used by do_i_need_to_upgrade."""
        return self._logger


def default_host(dist_name: str = "do_i_need_to_upgrade") -> Host:
    """Return a GenericHost for dist_name with a per-user cache dir.

    Args:
        dist_name: The distribution name to check. Defaults to 'do_i_need_to_upgrade'.

    Returns:
        A Host instance ready to use.
    """
    return GenericHost(dist_name=dist_name)


__all__ = ["GenericHost", "Host", "default_host", "user_cache_dir"]
