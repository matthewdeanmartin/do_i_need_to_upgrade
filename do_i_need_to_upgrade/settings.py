"""Programmatic configuration for embedding do_i_need_to_upgrade in a host app.

One frozen Settings dataclass holds every behavior knob. Overrides are
resolved with the precedence: environment variable > user config file >
app-supplied settings (constructor / pyproject.toml) > defaults.

End-user kill switch (works for any app embedding this library):

- ``DO_I_NEED_TO_UPGRADE=off`` disables checks entirely.
- ``DO_I_NEED_TO_UPGRADE=no-network`` allows cache reads but no PyPI fetches.
- A user config file (``~/.config/do_i_need_to_upgrade.toml`` or
  ``%APPDATA%\\do_i_need_to_upgrade.toml``) may set ``disabled``,
  ``no_network``, or ``disabled_for = ["dist-name", ...]``.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from .cache import COOLOFF, DEFAULT_TTL
from .host import GenericHost, user_cache_dir
from .pypi import PYPI_URL

Position = Literal["start", "end", "both", "off"]
Notify = Literal["exit-message", "return-only"]

ENV_VAR = "DO_I_NEED_TO_UPGRADE"
CONFIG_FILENAME = "do_i_need_to_upgrade.toml"
PYPROJECT_TABLE = "do_i_need_to_upgrade"

_POSITIONS = ("start", "end", "both", "off")
_NOTIFY_MODES = ("exit-message", "return-only")


def _load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, degrading to empty on py3.10 or any error.

    tomllib is stdlib from 3.11; on 3.10 config files are silently ignored
    (documented limitation — programmatic Settings still work everywhere).

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed table, or {} if unreadable/unparseable/unsupported.
    """
    try:
        import tomllib  # pylint: disable=import-outside-toplevel
    except ImportError:
        return {}
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def user_config_path() -> Path:
    """Return the platform path of the end-user override config file.

    Returns:
        Path to the user config file (may not exist).
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / CONFIG_FILENAME
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / CONFIG_FILENAME


@dataclass(frozen=True)
class Settings:
    """All behavior knobs for update checking, in one place.

    Attributes:
        dist_name: The distribution to check (the host app).
        cache_dir: Cache location; None means the per-user cache dir.
        check_ttl: How long a PyPI cache entry stays fresh.
        cooloff: Suppress upgrade nagging for releases younger than this.
        position: When checks run — start/end/both/off.
        allow_network: Whether PyPI fetches are permitted at all.
        include_prereleases: Treat pre-releases as upgrade candidates.
        check_dependencies: Also check the host's direct dependencies.
        notify: 'exit-message' prints the report to stderr at process exit
            (long-running-app mode); 'return-only' only returns the Report.
        index_url: PyPI JSON API URL template with a ``{name}`` placeholder;
            must be https. Supports private index mirrors.
        logger: Logger for diagnostics; None means a package-named logger.
    """

    dist_name: str
    cache_dir: Path | None = None
    check_ttl: timedelta = DEFAULT_TTL
    cooloff: timedelta = COOLOFF
    position: Position = "start"
    allow_network: bool = True
    include_prereleases: bool = False
    check_dependencies: bool = True
    notify: Notify = "return-only"
    index_url: str = PYPI_URL
    logger: logging.Logger | None = None

    def to_host(self) -> GenericHost:
        """Build the Host these settings describe.

        Returns:
            A GenericHost with this dist name, cache dir, and logger.
        """
        return GenericHost(
            dist_name=self.dist_name,
            cache_dir=self.cache_dir or user_cache_dir(self.dist_name),
            logger=self.logger,
        )

    def replace(self, **changes: Any) -> Settings:
        """Return a copy with the given fields replaced.

        Args:
            **changes: Field overrides.

        Returns:
            New Settings instance.
        """
        return dataclasses.replace(self, **changes)

    @classmethod
    def from_table(cls, table: dict[str, Any], dist_name: str) -> Settings:
        """Build Settings from a config table (pyproject tool table shape).

        Unknown keys are ignored; invalid values fall back to defaults.

        Recognized keys: enabled (bool), position, notify, cooloff_days,
        check_ttl_hours, include_prereleases, check_dependencies,
        allow_network, cache_dir, index_url.

        Args:
            table: The parsed config mapping.
            dist_name: The distribution the settings are for.

        Returns:
            A Settings instance.
        """
        settings = cls(dist_name=dist_name)
        if table.get("enabled") is False:
            settings = settings.replace(position="off")
        position = table.get("position")
        if position in _POSITIONS:
            settings = settings.replace(position=position)
        notify = table.get("notify")
        if notify in _NOTIFY_MODES:
            settings = settings.replace(notify=notify)
        cooloff_days = table.get("cooloff_days")
        if isinstance(cooloff_days, (int, float)) and not isinstance(cooloff_days, bool) and cooloff_days >= 0:
            settings = settings.replace(cooloff=timedelta(days=cooloff_days))
        ttl_hours = table.get("check_ttl_hours")
        if isinstance(ttl_hours, (int, float)) and not isinstance(ttl_hours, bool) and ttl_hours > 0:
            settings = settings.replace(check_ttl=timedelta(hours=ttl_hours))
        for key in ("include_prereleases", "check_dependencies", "allow_network"):
            value = table.get(key)
            if isinstance(value, bool):
                settings = settings.replace(**{key: value})
        cache_dir = table.get("cache_dir")
        if isinstance(cache_dir, str) and cache_dir:
            settings = settings.replace(cache_dir=Path(cache_dir))
        index_url = table.get("index_url")
        if isinstance(index_url, str) and index_url.startswith("https://") and "{name}" in index_url:
            settings = settings.replace(index_url=index_url)
        return settings

    @classmethod
    def from_toml(cls, path: Path, dist_name: str) -> Settings:
        """Load Settings from a standalone TOML file.

        The file may either be a bare table of the recognized keys or a
        pyproject.toml (the ``[tool.do_i_need_to_upgrade]`` table is used).
        Useful for shipping defaults as package data in a wheel, where
        pyproject.toml is not installed.

        Args:
            path: The TOML file to read.
            dist_name: The distribution the settings are for.

        Returns:
            A Settings instance (defaults if the file is missing/invalid).
        """
        data = _load_toml(path)
        tool = data.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get(PYPROJECT_TABLE), dict):
            return cls.from_table(tool[PYPROJECT_TABLE], dist_name)
        return cls.from_table(data, dist_name)

    @classmethod
    def from_pyproject(cls, dist_name: str, start: Path | None = None) -> Settings:
        """Find pyproject.toml by walking up from start (default: cwd).

        This is the development-time path; installed apps should ship a
        package-data TOML and use from_toml, or construct Settings directly.

        Args:
            dist_name: The distribution the settings are for.
            start: Directory to start searching from.

        Returns:
            A Settings instance (defaults if no pyproject.toml is found).
        """
        current = (start or Path.cwd()).resolve()
        for candidate in (current, *current.parents):
            pyproject = candidate / "pyproject.toml"
            if pyproject.is_file():
                return cls.from_toml(pyproject, dist_name)
        return cls(dist_name=dist_name)

    def resolve(self) -> Settings:
        """Apply end-user overrides: user config file, then environment.

        Precedence (weakest to strongest): these settings < user config
        file < ``DO_I_NEED_TO_UPGRADE`` environment variable.

        Returns:
            A new Settings with user overrides applied.
        """
        settings = self

        table = _load_toml(user_config_path())
        if table:
            disabled_for = table.get("disabled_for")
            globally_disabled = table.get("disabled") is True
            per_dist_disabled = isinstance(disabled_for, list) and self.dist_name in disabled_for
            if globally_disabled or per_dist_disabled:
                settings = settings.replace(position="off")
            if table.get("no_network") is True:
                settings = settings.replace(allow_network=False)

        env = os.environ.get(ENV_VAR, "").strip().lower()
        if env in {"off", "0", "false", "disabled"}:
            settings = settings.replace(position="off")
        elif env in {"no-network", "no_network", "cache-only"}:
            settings = settings.replace(allow_network=False)

        return settings


__all__ = ["ENV_VAR", "Notify", "Position", "Settings", "user_config_path"]
