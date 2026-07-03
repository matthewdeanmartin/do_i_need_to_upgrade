"""pip-check-style integrity verification.

Walks installed distributions via importlib.metadata and validates each
Requires-Dist line with the ``packaging`` library (already a runtime
dependency), so specifiers, epochs, post/local versions, and environment
markers all follow PEP 440/508 exactly.
"""

from __future__ import annotations

from importlib import metadata

from packaging.markers import InvalidMarker, UndefinedComparison, UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion


def _marker_applies(requirement: Requirement) -> bool:
    """Return True if the requirement's marker applies to this environment.

    ``extra`` markers evaluate against an empty extra, so optional-extra
    requirements are skipped. Markers that cannot be evaluated are treated
    as applicable so a required dependency is never silently missed.

    Args:
        requirement: The parsed requirement.

    Returns:
        True if the requirement applies to the current environment.
    """
    if requirement.marker is None:
        return True
    try:
        return requirement.marker.evaluate({"extra": ""})
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        return True


def run() -> list[str]:
    """Return a list of human-readable integrity problems. Empty = clean.

    Only requirements whose environment markers apply to the current
    interpreter are checked. ``extra`` requirements are skipped because they
    describe optional install groups, not runtime requirements.

    Returns:
        List of problem description strings. Empty list means everything is clean.
    """
    problems: list[str] = []
    all_dists = list(metadata.distributions())
    installed_versions: dict[str, str] = {}
    for dist in all_dists:
        name = dist.metadata["Name"] if dist.metadata else None
        if name:
            installed_versions[canonicalize_name(name)] = dist.version

    for dist in all_dists:
        origin = dist.metadata["Name"] if dist.metadata else None
        if not origin:
            continue
        for requirement_str in dist.requires or []:
            try:
                requirement = Requirement(requirement_str)
            except InvalidRequirement:
                continue
            if not _marker_applies(requirement):
                continue
            installed = installed_versions.get(canonicalize_name(requirement.name))
            if not installed:
                problems.append(f"{origin} requires {requirement.name} which is not installed")
                continue
            try:
                satisfied = requirement.specifier.contains(installed, prereleases=True)
            except InvalidVersion:
                continue
            if not satisfied:
                problems.append(
                    f"{origin} requires {requirement.name}{requirement.specifier} but {installed} is installed"
                )
    return problems


__all__ = ["run"]
