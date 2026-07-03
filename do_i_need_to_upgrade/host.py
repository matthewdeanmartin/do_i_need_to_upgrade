"""Host adapter protocol for do_i_need_to_upgrade.

The Host protocol is the only coupling point between this library and a host
application. Implement it (or use GenericHost) to integrate with any app.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Host(Protocol):
    """Minimal protocol a host application must satisfy."""

    @property
    def dist_name(self) -> str:
        """Name of the distribution this host represents (e.g. 'my-app')."""
        ...

    @property
    def cache_dir(self) -> Path:
        """Directory where do_i_need_to_upgrade may write its sidecar cache."""
        ...

    @property
    def logger(self) -> logging.Logger:
        """Logger used by do_i_need_to_upgrade."""
        ...


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
            cache_dir: Where to store the cache. Defaults to a tempdir subdirectory.
            logger: Logger instance. Defaults to logging.getLogger(dist_name).
        """
        self._dist_name = dist_name
        self._cache_dir = cache_dir or Path(tempfile.gettempdir()) / f"do_i_need_to_upgrade-{dist_name}"
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
    """Return a GenericHost for dist_name with a temp-based cache dir.

    Args:
        dist_name: The distribution name to check. Defaults to 'do_i_need_to_upgrade'.

    Returns:
        A Host instance ready to use.
    """
    base = Path(tempfile.gettempdir()) / f"do_i_need_to_upgrade-{dist_name}"
    return GenericHost(dist_name=dist_name, cache_dir=base)


__all__ = ["GenericHost", "Host", "default_host"]
