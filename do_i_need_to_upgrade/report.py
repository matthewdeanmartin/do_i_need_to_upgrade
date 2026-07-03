"""Report dataclasses and ANSI text rendering."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TextIO


def _can_use_color(stream: TextIO) -> bool:
    """Return True if ANSI color output is safe to use on the given stream.

    Args:
        stream: The stream the text will be written to.

    Returns:
        True if color output is permitted by the current environment.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CI"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_BLUE = "\033[94m"
_RESET = "\033[0m"


def _c(text: str, code: str, stream: TextIO) -> str:
    """Wrap text in an ANSI color code if color is enabled for stream.

    Args:
        text: The text to colorize.
        code: The ANSI escape code prefix.
        stream: The stream the text will be written to.

    Returns:
        Colorized string or plain text if color is disabled.
    """
    if _can_use_color(stream):
        return f"{code}{text}{_RESET}"
    return text


@dataclass(frozen=True)
class VersionInfo:
    """Version metadata for one tracked package."""

    name: str
    installed: str
    latest: str | None
    latest_published: datetime | None
    age_days: float | None
    is_upgrade_available: bool
    is_in_cooloff: bool
    is_prerelease: bool = False
    is_yanked: bool = False
    is_dev: bool = False

    @property
    def actionable(self) -> bool:
        """True if there is an upgrade the user should actually take.

        Returns:
            True when an upgrade is available, not suppressed by cooloff,
            not yanked, and not a dev release.
        """
        return self.is_upgrade_available and not self.is_in_cooloff and not self.is_yanked and not self.is_dev


@dataclass(frozen=True)
class Vulnerability:
    """A single vulnerability finding from an audit tool."""

    name: str
    installed: str
    advisory_id: str
    severity: str | None
    fix_versions: tuple[str, ...]
    source: str

    @property
    def actionable(self) -> bool:
        """True if a fix is available.

        Returns:
            True when at least one fix version is listed.
        """
        return bool(self.fix_versions)


@dataclass(frozen=True)
class Report:
    """Top-level result returned by check_for_updates / run_audit."""

    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    host_dist: VersionInfo | None = None
    dependencies: tuple[VersionInfo, ...] = ()
    vulnerabilities: tuple[Vulnerability, ...] = ()
    notes: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True if there is nothing actionable to report.

        Returns:
            True when no actionable upgrades or vulnerabilities exist.
        """
        if self.host_dist and self.host_dist.actionable:
            return False
        if any(dep.actionable for dep in self.dependencies):
            return False
        return not any(vuln.actionable for vuln in self.vulnerabilities)

    def render_text(self, stream: TextIO | None = None) -> str:
        """Render the report as a human-readable string.

        Args:
            stream: The stream the text is destined for; used only to decide
                whether ANSI color is safe. Defaults to sys.stdout.

        Returns:
            Multi-line string; empty string if nothing to report.
        """
        out = stream if stream is not None else sys.stdout
        lines: list[str] = []

        if self.host_dist and self.host_dist.actionable:
            hd = self.host_dist
            lines.append(_c(f"[update] {hd.name} {hd.installed} -> {hd.latest} is available", _YELLOW, out))
        elif self.host_dist and self.host_dist.is_yanked:
            hd = self.host_dist
            lines.append(_c(f"[warning] {hd.name} {hd.installed} has been YANKED from PyPI!", _RED, out))

        upgradable = [d for d in self.dependencies if d.actionable]
        if upgradable:
            lines.append(f"[update] {len(upgradable)} dependencies have upgrades available:")
            for dep in upgradable:
                lines.append(_c(f"  - {dep.name} {dep.installed} -> {dep.latest}", _GREEN, out))

        actionable_vulns = [v for v in self.vulnerabilities if v.actionable]
        if actionable_vulns:
            lines.append(_c(f"[security] {len(actionable_vulns)} vulnerabilities with available fixes:", _RED, out))
            for vuln in actionable_vulns:
                fix = ", ".join(vuln.fix_versions) or "n/a"
                sev = vuln.severity or "unknown"
                lines.append(f"  - {vuln.name} {vuln.installed} {vuln.advisory_id} [{sev}] fix: {fix}")

        for note in self.notes:
            lines.append(_c(f"[note] {note}", _BLUE, out))
        for err in self.errors:
            lines.append(f"[warn] {err}")
        return "\n".join(lines)


__all__ = ["Report", "VersionInfo", "Vulnerability"]
