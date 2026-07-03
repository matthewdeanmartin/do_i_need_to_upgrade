"""Public API for do_i_need_to_upgrade.

This module orchestrates the cache, PyPI client, installed-dep walker, and
audit runner into the small public surface documented in __init__.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from do_i_need_to_upgrade import background, installed
from do_i_need_to_upgrade import pypi as pypi_module
from do_i_need_to_upgrade import upgrade as upgrade_module
from do_i_need_to_upgrade.audit import run_available_audit
from do_i_need_to_upgrade.cache import COOLOFF, Cache, parse_iso, utcnow
from do_i_need_to_upgrade.host import Host, default_host
from do_i_need_to_upgrade.report import Report, VersionInfo
from do_i_need_to_upgrade.upgrade import UpgradeResult

Position = Literal["start", "end", "both", "off"]


def _build_version_info(
    name: str,
    installed_version: str,
    cache: Cache,
    include_prereleases: bool = False,
) -> VersionInfo:
    """Construct a VersionInfo from cache data for a single package.

    Args:
        name: Package name.
        installed_version: Currently installed version string.
        cache: The loaded Cache instance.
        include_prereleases: Whether to treat pre-releases as upgrade candidates.

    Returns:
        A populated VersionInfo dataclass.
    """
    entry = cache.get_package(name)
    if not entry:
        return VersionInfo(
            name=name,
            installed=installed_version,
            latest=None,
            latest_published=None,
            age_days=None,
            is_upgrade_available=False,
            is_in_cooloff=False,
        )
    latest = entry.get("latest")
    published = parse_iso(entry.get("published"))
    is_prerelease = bool(entry.get("is_prerelease", False))
    is_yanked = bool(entry.get("is_yanked", False))
    is_dev = bool(entry.get("is_dev", False))
    age_days: float | None = None
    is_cooloff = False
    if published:
        age = utcnow() - published
        age_days = age.total_seconds() / 86400.0
        is_cooloff = age < COOLOFF
    target_key = f"{name}=={latest}" if latest else None
    snoozed = cache.is_snoozed(target_key) if target_key else False
    upgrade_available = bool(latest and latest != installed_version and not snoozed)
    return VersionInfo(
        name=name,
        installed=installed_version,
        latest=latest,
        latest_published=published,
        age_days=age_days,
        is_upgrade_available=upgrade_available,
        is_in_cooloff=is_cooloff,
        is_prerelease=is_prerelease,
        is_yanked=is_yanked,
        is_dev=is_dev,
    )


def _refresh_pypi(
    host: Host,
    names: list[str],
    include_prereleases: bool = False,
) -> list[str]:
    """Fetch missing/stale entries for the given package names.

    Args:
        host: The Host instance.
        names: Package names to refresh.
        include_prereleases: Whether to consider pre-releases.

    Returns:
        List of error strings (empty if all succeeded).
    """
    cache = Cache.load(host.cache_dir)
    errors: list[str] = []
    changed = False
    installed_ver = installed.host_version(host.dist_name) or "0.0.0"
    for name in names:
        if cache.is_fresh(name):
            continue
        try:
            detail = pypi_module.get_version_detail(
                name,
                current_version=installed_ver,
                include_prereleases=include_prereleases,
            )
        except pypi_module.PypiError as exc:
            errors.append(str(exc))
            host.logger.debug("pypi fetch failed: %s", exc)
            continue
        cache.put_package(name, detail.latest, detail.published)
        # Store extra fields that VersionInfo needs
        cache.data["pypi"][name]["is_prerelease"] = detail.is_prerelease
        cache.data["pypi"][name]["is_yanked"] = detail.is_yanked
        cache.data["pypi"][name]["is_dev"] = detail.is_dev
        changed = True
    if changed:
        cache.save()
    return errors


def check_for_updates(
    host: Host | None = None,
    position: Position = "start",
    allow_network: bool = True,
    include_prereleases: bool = False,
) -> Report:
    """Return a cached-then-refreshed freshness report.

    ``position="start"`` runs cache-only in the foreground and (if allow_network)
    schedules a background refresh. ``position="end"`` refreshes synchronously so
    the next start is instant. ``position="both"`` does both. ``position="off"``
    returns an empty report.

    Args:
        host: Host instance. Defaults to default_host().
        position: When to do the synchronous refresh. One of start/end/both/off.
        allow_network: Whether background/synchronous network calls are permitted.
        include_prereleases: Whether to include pre-releases as upgrade candidates.

    Returns:
        A Report with the current upgrade status.
    """
    active_host = host or default_host()
    if position == "off":
        return Report()

    cache = Cache.load(active_host.cache_dir)
    cache.prune_snoozes()
    host_installed = installed.host_version(active_host.dist_name)
    if host_installed is None:
        return Report(
            errors=(f"host distribution {active_host.dist_name!r} is not installed",),
        )
    deps = installed.direct_dependencies(active_host.dist_name)
    names_to_track = [active_host.dist_name] + [name for name, _ in deps]

    errors: list[str]
    if position in {"end", "both"}:
        errors = _refresh_pypi(active_host, names_to_track, include_prereleases=include_prereleases)
        cache = Cache.load(active_host.cache_dir)
    elif allow_network:
        stale = [n for n in names_to_track if not cache.is_fresh(n)]
        if stale:

            def run_refresh() -> None:
                _refresh_pypi(active_host, stale, include_prereleases=include_prereleases)

            background.spawn(run_refresh)
        errors = []
    else:
        errors = []

    host_info = _build_version_info(active_host.dist_name, host_installed, cache, include_prereleases)
    dep_infos = tuple(_build_version_info(name, version, cache, include_prereleases) for name, version in deps)

    notes: list[str] = []
    all_infos = [host_info, *dep_infos]
    if any(info.is_in_cooloff for info in all_infos):
        notes.append("some upgrades are suppressed during a 14-day cooloff window")

    report = Report(
        host_dist=host_info,
        dependencies=dep_infos,
        notes=tuple(notes),
        errors=tuple(errors),
    )

    # Register exit message for the background-check use case
    if position == "start" and not report.is_empty:
        msg = report.render_text()
        if msg:
            background.register_exit_message(msg)

    return report


def run_audit(host: Host | None = None, force: bool = False) -> Report:
    """Run an opportunistic vulnerability audit.

    Only runs if at least one upgrade is actionable (i.e., there is something
    the user can do about a finding), unless ``force=True``.

    Args:
        host: Host instance. Defaults to default_host().
        force: Run audit even if no upgrades are pending.

    Returns:
        A Report that may include Vulnerability entries.
    """
    active_host = host or default_host()
    report = check_for_updates(host=active_host, position="start", allow_network=False)

    any_actionable = bool(report.host_dist and report.host_dist.actionable) or any(
        dep.actionable for dep in report.dependencies
    )
    if not any_actionable and not force:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: nothing to upgrade, no actionable fix possible",),
        )

    vulns, tool = run_available_audit()
    if tool is None:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: no audit tool available on PATH (pip-audit, safety, uv)",),
        )

    cache = Cache.load(active_host.cache_dir)
    cache.set_audit(tool=tool, summary={"vuln_count": len(vulns)})
    cache.save()

    return Report(
        generated_at=datetime.now(timezone.utc),
        host_dist=report.host_dist,
        dependencies=report.dependencies,
        vulnerabilities=tuple(vulns),
        notes=(f"audit tool: {tool}",),
    )


def self_upgrade(host: Host | None = None, dry_run: bool = False) -> UpgradeResult:
    """Self-upgrade the host distribution.

    Args:
        host: Host instance. Defaults to default_host().
        dry_run: Print the upgrade command without executing it.

    Returns:
        An UpgradeResult describing what happened.
    """
    active_host = host or default_host()
    return upgrade_module.perform(active_host.dist_name, dry_run=dry_run)


def self_check(host: Host | None = None) -> list[str]:
    """Verify that all installed distributions satisfy their Requires-Dist.

    Args:
        host: Unused; present for API symmetry.

    Returns:
        List of human-readable integrity problem strings. Empty = clean.
    """
    from do_i_need_to_upgrade import integrity_check

    return integrity_check.run()


def clear_cache(host: Host | None = None) -> None:
    """Clear the sidecar cache.

    Args:
        host: Host instance. Defaults to default_host().
    """
    active_host = host or default_host()
    cache = Cache.load(active_host.cache_dir)
    cache.clear()
    cache.save()


def snooze(target: str, days: int, host: Host | None = None) -> None:
    """Snooze upgrade notifications for a specific package version.

    Args:
        target: Target identifier, e.g. 'my-app==1.2.3'.
        days: Number of days to snooze.
        host: Host instance. Defaults to default_host().
    """
    active_host = host or default_host()
    cache = Cache.load(active_host.cache_dir)
    cache.snooze(target, days)
    cache.save()


__all__ = [
    "Position",
    "check_for_updates",
    "clear_cache",
    "run_audit",
    "self_check",
    "self_upgrade",
    "snooze",
]
