"""Resolve where a distribution is installed, beyond the current environment.

The CLI use case is checking *other* apps ("is ruff out of date?"), which may
live in the current environment, a uv tool venv, a pipx venv, or just on
PATH. Resolvers are tried in that order. Tool listings (``uv tool list``,
``pipx list``) are fetched once per process and cached.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from . import installed
from .install_method import InstallMethod, detect

RESOLVE_TIMEOUT = 10.0
_UV_TOOL_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s+v?(\S+)\s*$")
_VERSION_IN_TEXT = re.compile(r"(\d+(?:\.\d+)+(?:[A-Za-z0-9.!+-]*)?)")


@dataclass(frozen=True)
class Target:
    """A distribution to check, wherever it is installed."""

    name: str
    installed_version: str | None
    install_method: InstallMethod
    source: str
    """Which resolver found it: 'env', 'uv-tool', 'pipx', 'path', or 'none'."""


def _run(argv: list[str]) -> str | None:
    """Run a command and return stdout on success, None on any failure.

    Args:
        argv: Command argument list.

    Returns:
        Stdout string when the command exits 0, otherwise None.
    """
    try:
        proc = subprocess.run(  # nosec B603
            argv,
            capture_output=True,
            text=True,
            timeout=RESOLVE_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _parse_uv_tool_list(text: str) -> dict[str, str]:
    """Parse ``uv tool list`` output into {name: version}.

    Lines look like ``ruff v0.4.4`` followed by ``- ruff`` entrypoint lines.

    Args:
        text: Raw stdout from ``uv tool list``.

    Returns:
        Mapping of tool name to version.
    """
    versions: dict[str, str] = {}
    for line in text.splitlines():
        match = _UV_TOOL_LINE.match(line.strip())
        if match:
            versions[match.group(1)] = match.group(2)
    return versions


def _parse_pipx_list(text: str) -> dict[str, str]:
    """Parse ``pipx list --json`` output into {name: version}.

    Args:
        text: Raw stdout from ``pipx list --json``.

    Returns:
        Mapping of package name to version.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    venvs = payload.get("venvs")
    if not isinstance(venvs, dict):
        return {}
    versions: dict[str, str] = {}
    for venv in venvs.values():
        if not isinstance(venv, dict):
            continue
        main = (venv.get("metadata") or {}).get("main_package") or {}
        if not isinstance(main, dict):
            continue
        name = main.get("package")
        version = main.get("package_version")
        if isinstance(name, str) and isinstance(version, str):
            versions[name] = version
    return versions


@lru_cache(maxsize=1)
def uv_tool_versions() -> dict[str, str]:
    """Return {name: version} for uv-managed tools, fetched once per process.

    Returns:
        Mapping of tool name to version; empty if uv is unavailable.
    """
    if not shutil.which("uv"):
        return {}
    stdout = _run(["uv", "tool", "list"])
    return _parse_uv_tool_list(stdout) if stdout else {}


@lru_cache(maxsize=1)
def pipx_versions() -> dict[str, str]:
    """Return {name: version} for pipx-managed apps, fetched once per process.

    Returns:
        Mapping of package name to version; empty if pipx is unavailable.
    """
    if not shutil.which("pipx"):
        return {}
    stdout = _run(["pipx", "list", "--json"])
    return _parse_pipx_list(stdout) if stdout else {}


def _version_from_exe(name: str) -> str | None:
    """Best-effort version probe: run ``<name> --version`` and parse it.

    Args:
        name: Executable name found on PATH.

    Returns:
        Version string, or None if it could not be determined.
    """
    stdout = _run([name, "--version"])
    if not stdout:
        return None
    match = _VERSION_IN_TEXT.search(stdout)
    return match.group(1) if match else None


def _normalized_lookup(versions: dict[str, str], name: str) -> str | None:
    """Look up name in versions, tolerating -/_ and case differences.

    Args:
        versions: Mapping of package name to version.
        name: Name to look up.

    Returns:
        Version string or None.
    """
    if name in versions:
        return versions[name]
    wanted = name.lower().replace("_", "-")
    for candidate, version in versions.items():
        if candidate.lower().replace("_", "-") == wanted:
            return version
    return None


def resolve(name: str) -> Target:
    """Resolve a distribution to wherever it is installed.

    Tries the current environment, then uv tools, then pipx, then a bare
    executable on PATH. A Target is always returned; ``source == "none"``
    (with ``installed_version is None``) means nothing was found.

    Args:
        name: Distribution or executable name.

    Returns:
        A Target describing where (or whether) the distribution is installed.
    """
    env_version = installed.host_version(name)
    if env_version is not None:
        return Target(name=name, installed_version=env_version, install_method=detect(name), source="env")

    uv_version = _normalized_lookup(uv_tool_versions(), name)
    if uv_version is not None:
        return Target(name=name, installed_version=uv_version, install_method=InstallMethod.UV_TOOL, source="uv-tool")

    pipx_version = _normalized_lookup(pipx_versions(), name)
    if pipx_version is not None:
        return Target(name=name, installed_version=pipx_version, install_method=InstallMethod.PIPX, source="pipx")

    if shutil.which(name):
        return Target(
            name=name,
            installed_version=_version_from_exe(name),
            install_method=InstallMethod.UNKNOWN,
            source="path",
        )

    return Target(name=name, installed_version=None, install_method=InstallMethod.UNKNOWN, source="none")


def resolve_all(names: list[str]) -> list[Target]:
    """Resolve several names, preserving order and dropping duplicates.

    Args:
        names: Distribution names to resolve.

    Returns:
        List of Targets, one per unique name.
    """
    targets: list[Target] = []
    seen: set[str] = set()
    for name in names:
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        targets.append(resolve(name))
    return targets


def parse_requirements_file(path: Path) -> list[str]:
    """Extract distribution names from a requirements.txt-style file.

    Skips comments, blank lines, pip options (``-e``, ``--index-url``, ...),
    and anything that does not parse as a PEP 508 requirement.

    Args:
        path: Path to the requirements file.

    Returns:
        List of distribution names in file order, deduplicated.
    """
    names: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        key = requirement.name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        names.append(requirement.name)
    return names


__all__ = ["Target", "parse_requirements_file", "pipx_versions", "resolve", "resolve_all", "uv_tool_versions"]
