"""Detect how the host distribution was installed.

Used by upgrade.py to select the appropriate upgrade command.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from importlib import metadata
from pathlib import Path


class InstallMethod(str, Enum):
    """Enum of known installation methods."""

    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    VENV_PIP = "venv-pip"
    USER_PIP = "user-pip"
    SYSTEM_PIP = "system-pip"
    EDITABLE = "editable"
    UNKNOWN = "unknown"


def is_editable(dist: metadata.Distribution) -> bool:
    """Return True if the distribution is installed in editable mode.

    Args:
        dist: The Distribution object to inspect.

    Returns:
        True if installed as editable (development) install.
    """
    try:
        raw = dist.read_text("direct_url.json")
    except Exception:
        return False
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False
    dir_info = data.get("dir_info") or {}
    return bool(dir_info.get("editable"))


def dist_location(dist: metadata.Distribution) -> Path | None:
    """Return the filesystem location of an installed distribution.

    Args:
        dist: The Distribution object.

    Returns:
        Resolved Path to the distribution directory, or None.
    """
    locate = getattr(dist, "locate_file", None)
    try:
        if locate is not None:
            return Path(locate("")).resolve()
    except Exception:
        pass
    origin = getattr(dist, "_path", None)
    return Path(origin).resolve() if origin else None


def detect(dist_name: str) -> InstallMethod:
    """Detect the install method for a distribution.

    Args:
        dist_name: The distribution name to inspect.

    Returns:
        The detected InstallMethod enum value.
    """
    try:
        dist = metadata.distribution(dist_name)
    except metadata.PackageNotFoundError:
        return InstallMethod.UNKNOWN

    if is_editable(dist):
        return InstallMethod.EDITABLE

    location = dist_location(dist)
    location_str = str(location).replace("\\", "/").lower() if location else ""

    if "/uv/tools/" in location_str:
        return InstallMethod.UV_TOOL
    if "/pipx/venvs/" in location_str:
        return InstallMethod.PIPX

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        return InstallMethod.VENV_PIP

    try:
        import site

        user_site = (site.getusersitepackages() or "").replace("\\", "/").lower()
    except Exception:
        user_site = ""
    if user_site and user_site in location_str:
        return InstallMethod.USER_PIP

    return InstallMethod.SYSTEM_PIP


def upgrade_argv(method: InstallMethod, dist_name: str) -> list[str] | None:
    """Return the argv for the appropriate upgrade command.

    Args:
        method: The detected install method.
        dist_name: The distribution name to upgrade.

    Returns:
        The command argument list, or None if upgrading is not supported.
    """
    if method == InstallMethod.UV_TOOL:
        return ["uv", "tool", "upgrade", dist_name]
    if method == InstallMethod.PIPX:
        return ["pipx", "upgrade", dist_name]
    if method == InstallMethod.VENV_PIP:
        return [sys.executable, "-m", "pip", "install", "--upgrade", dist_name]
    if method == InstallMethod.USER_PIP:
        return [sys.executable, "-m", "pip", "install", "--user", "--upgrade", dist_name]
    if method == InstallMethod.SYSTEM_PIP:
        return [sys.executable, "-m", "pip", "install", "--upgrade", dist_name]
    return None


__all__ = ["InstallMethod", "detect", "dist_location", "is_editable", "upgrade_argv"]
