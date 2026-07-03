"""Drop-in application self-upgrade checker and vulnerability auditor.

This package is stdlib-only at runtime (plus ``packaging`` for version comparison).
External tools (pip-audit, safety, uv) are used opportunistically when present
on PATH but never required.

Public API::

    check_for_updates(host, position="start") -> Report
    run_audit(host) -> Report
    self_upgrade(host, dry_run=False) -> UpgradeResult
    self_check(host) -> list[str]
    clear_cache(host) -> None
    snooze(target, days, host) -> None

Standalone CLI::

    python -m do_i_need_to_upgrade --help
"""

from __future__ import annotations

from .__about__ import __version__
from .api import (
    check_for_updates,
    check_targets,
    clear_cache,
    run_audit,
    self_check,
    self_upgrade,
    snooze,
    upgrade_target,
)
from .host import GenericHost, Host, default_host
from .integrate import (
    add_check_command,
    add_upgrade_command,
    install_background_check,
    run_if_upgrade_command,
)
from .report import Report, VersionInfo, Vulnerability
from .resolvers import Target, resolve, resolve_all
from .settings import Settings

__all__ = [
    "GenericHost",
    "Host",
    "Report",
    "Settings",
    "Target",
    "VersionInfo",
    "Vulnerability",
    "__version__",
    "add_check_command",
    "add_upgrade_command",
    "check_for_updates",
    "check_targets",
    "clear_cache",
    "default_host",
    "install_background_check",
    "resolve",
    "resolve_all",
    "run_audit",
    "run_if_upgrade_command",
    "self_check",
    "self_upgrade",
    "snooze",
    "upgrade_target",
]
