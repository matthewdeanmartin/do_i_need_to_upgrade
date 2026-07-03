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

from do_i_need_to_upgrade.__about__ import __version__
from do_i_need_to_upgrade.api import check_for_updates, clear_cache, run_audit, self_check, self_upgrade, snooze
from do_i_need_to_upgrade.host import GenericHost, Host, default_host
from do_i_need_to_upgrade.report import Report, VersionInfo, Vulnerability

__all__ = [
    "GenericHost",
    "Host",
    "Report",
    "VersionInfo",
    "Vulnerability",
    "__version__",
    "check_for_updates",
    "clear_cache",
    "default_host",
    "run_audit",
    "self_check",
    "self_upgrade",
    "snooze",
]
