"""Public API for do_i_need_to_upgrade.

This module orchestrates the cache, PyPI client, installed-dep walker, and
audit runner into the small public surface documented in __init__.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from packaging.version import InvalidVersion, Version

from . import background, installed, integrity_check
from . import pypi as pypi_module
from . import upgrade as upgrade_module
from .audit import run_available_audit
from .cache import COOLOFF, DEFAULT_TTL, Cache, parse_iso, utcnow
from .host import Host, default_host
from .report import Report, VersionInfo
from .resolvers import Target
from .settings import Position, Settings
from .upgrade import UpgradeResult


def _host_from(host: Host | None, settings: Settings | None) -> Host:
    """Pick the effective Host: settings win, then host, then the default.

    Args:
        host: Optional explicit Host.
        settings: Optional Settings whose to_host() takes precedence.

    Returns:
        The Host to operate on.
    """
    if settings is not None:
        return settings.to_host()
    return host or default_host()


def _is_newer(latest: str, installed_version: str) -> bool:
    """Return True if latest is a strictly newer version than installed.

    Falls back to string inequality only when a version cannot be parsed,
    so a local dev build newer than PyPI is never reported as an upgrade.

    Args:
        latest: Candidate version string.
        installed_version: Currently installed version string.

    Returns:
        True if latest > installed_version.
    """
    try:
        return Version(latest) > Version(installed_version)
    except InvalidVersion:
        return latest != installed_version


def _build_version_info(
    name: str,
    installed_version: str,
    cache: Cache,
    cooloff: timedelta = COOLOFF,
) -> VersionInfo:
    """Construct a VersionInfo from cache data for a single package.

    Args:
        name: Package name.
        installed_version: Currently installed version string.
        cache: The loaded Cache instance.
        cooloff: Age below which a release counts as in-cooloff.

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
        is_cooloff = age < cooloff
    target_key = f"{name}=={latest}" if latest else None
    snoozed = cache.is_snoozed(target_key) if target_key else False
    upgrade_available = bool(latest and _is_newer(latest, installed_version) and not snoozed)
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
    packages: dict[str, str],
    include_prereleases: bool = False,
    ttl: timedelta = DEFAULT_TTL,
    index_url: str = pypi_module.PYPI_URL,
) -> list[str]:
    """Fetch missing/stale entries for the given packages.

    Args:
        host: The Host instance.
        packages: Mapping of package name to its installed version. Each
            package's own version is used for yanked detection.
        include_prereleases: Whether to consider pre-releases.
        ttl: Cache freshness window; entries younger than this are skipped.
        index_url: Package index JSON URL template.

    Returns:
        List of error strings (empty if all succeeded).
    """
    cache = Cache.load(host.cache_dir)
    errors: list[str] = []
    changed = False
    for name, installed_ver in packages.items():
        if cache.is_fresh(name, ttl=ttl):
            continue
        try:
            detail = pypi_module.get_version_detail(
                name,
                current_version=installed_ver,
                include_prereleases=include_prereleases,
                url_template=index_url,
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
    notify_at_exit: bool = True,
    settings: Settings | None = None,
) -> Report:
    """Return a cached-then-refreshed freshness report.

    ``position="start"`` runs cache-only in the foreground and (if allow_network)
    schedules a background refresh. ``position="end"`` refreshes synchronously so
    the next start is instant. ``position="both"`` does both. ``position="off"``
    returns an empty report.

    The background refresh runs on a daemon thread and is designed for
    long-running applications: the process must stay alive for a few seconds
    for the refresh to land in the cache. Short-lived CLI invocations should
    use ``position="end"`` or ``position="both"`` instead.

    Args:
        host: Host instance. Defaults to default_host().
        position: When to do the synchronous refresh. One of start/end/both/off.
        allow_network: Whether background/synchronous network calls are permitted.
        include_prereleases: Whether to include pre-releases as upgrade candidates.
        notify_at_exit: With ``position="start"``, also print the report to
            stderr when the program exits. Set False when the caller displays
            the report itself.
        settings: When given, wins over host/position/allow_network/
            include_prereleases/notify_at_exit and supplies TTL, cooloff,
            dependency checking, and index URL. End-user overrides (env var,
            user config file) are applied via settings.resolve().

    Returns:
        A Report with the current upgrade status.
    """
    ttl = DEFAULT_TTL
    cooloff = COOLOFF
    check_dependencies = True
    index_url = pypi_module.PYPI_URL
    if settings is not None:
        resolved = settings.resolve()
        active_host: Host = resolved.to_host()
        position = resolved.position
        allow_network = resolved.allow_network
        include_prereleases = resolved.include_prereleases
        notify_at_exit = resolved.notify == "exit-message"
        ttl = resolved.check_ttl
        cooloff = resolved.cooloff
        check_dependencies = resolved.check_dependencies
        index_url = resolved.index_url
    else:
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
    deps = installed.direct_dependencies(active_host.dist_name) if check_dependencies else []
    packages_to_track: dict[str, str] = {active_host.dist_name: host_installed, **dict(deps)}

    errors: list[str]
    if position in {"end", "both"}:
        errors = _refresh_pypi(
            active_host, packages_to_track, include_prereleases=include_prereleases, ttl=ttl, index_url=index_url
        )
        cache = Cache.load(active_host.cache_dir)
    elif allow_network:
        stale = {n: v for n, v in packages_to_track.items() if not cache.is_fresh(n, ttl=ttl)}
        if stale:

            def run_refresh() -> None:
                _refresh_pypi(active_host, stale, include_prereleases=include_prereleases, ttl=ttl, index_url=index_url)

            background.spawn(run_refresh)
        errors = []
    else:
        errors = []

    host_info = _build_version_info(active_host.dist_name, host_installed, cache, cooloff=cooloff)
    dep_infos = tuple(_build_version_info(name, version, cache, cooloff=cooloff) for name, version in deps)

    notes: list[str] = []
    all_infos = [host_info, *dep_infos]
    if any(info.is_upgrade_available and info.is_in_cooloff for info in all_infos):
        notes.append(f"some upgrades are suppressed during a {cooloff.days}-day cooloff window")

    report = Report(
        host_dist=host_info,
        dependencies=dep_infos,
        notes=tuple(notes),
        errors=tuple(errors),
    )

    # Register exit message for the background-check use case
    if notify_at_exit and position == "start" and not report.is_empty:
        msg = report.render_text(stream=sys.stderr)
        if msg:
            background.register_exit_message(msg)

    return report


def check_targets(
    targets: list[Target],
    host: Host | None = None,
    allow_network: bool = True,
    include_prereleases: bool = False,
    settings: Settings | None = None,
) -> Report:
    """Check arbitrary resolved targets (other apps/packages) for upgrades.

    Unlike check_for_updates, this does not inspect the host distribution's
    dependency tree — it checks exactly the given targets, refreshing PyPI
    metadata synchronously when the network is allowed. Targets that are not
    installed anywhere still get their latest PyPI version reported via a note.

    Args:
        targets: Resolved targets (see resolvers.resolve / resolve_all).
        host: Host instance supplying the cache location. Defaults to
            default_host().
        allow_network: Whether to refresh stale entries from PyPI.
        include_prereleases: Whether to include pre-releases as candidates.
        settings: When given, supplies host, network policy, TTL, cooloff,
            and index URL (end-user overrides applied via resolve()).

    Returns:
        A Report with one VersionInfo per target in ``dependencies``.
    """
    ttl = DEFAULT_TTL
    cooloff = COOLOFF
    index_url = pypi_module.PYPI_URL
    if settings is not None:
        resolved = settings.resolve()
        active_host: Host = resolved.to_host()
        allow_network = resolved.allow_network
        include_prereleases = resolved.include_prereleases
        ttl = resolved.check_ttl
        cooloff = resolved.cooloff
        index_url = resolved.index_url
    else:
        active_host = host or default_host()
    cache = Cache.load(active_host.cache_dir)
    cache.prune_snoozes()

    packages = {t.name: (t.installed_version or "0.0.0") for t in targets}
    errors: list[str] = []
    if allow_network and packages:
        errors = _refresh_pypi(
            active_host, packages, include_prereleases=include_prereleases, ttl=ttl, index_url=index_url
        )
        cache = Cache.load(active_host.cache_dir)

    infos: list[VersionInfo] = []
    notes: list[str] = []
    for target in targets:
        if target.installed_version is None:
            entry = cache.get_package(target.name)
            latest = entry.get("latest") if entry else None
            notes.append(f"{target.name} is not installed; latest on PyPI is {latest or 'unknown'}")
            infos.append(
                VersionInfo(
                    name=target.name,
                    installed="(not installed)",
                    latest=latest,
                    latest_published=None,
                    age_days=None,
                    is_upgrade_available=False,
                    is_in_cooloff=False,
                )
            )
            continue
        infos.append(_build_version_info(target.name, target.installed_version, cache, cooloff=cooloff))

    if any(info.is_upgrade_available and info.is_in_cooloff for info in infos):
        notes.append(f"some upgrades are suppressed during a {cooloff.days}-day cooloff window")

    return Report(dependencies=tuple(infos), notes=tuple(notes), errors=tuple(errors))


def upgrade_target(target: Target, dry_run: bool = False) -> UpgradeResult:
    """Upgrade a resolved target using its detected install method.

    Args:
        target: The resolved target to upgrade.
        dry_run: Print the upgrade command without executing it.

    Returns:
        An UpgradeResult describing what happened.
    """
    return upgrade_module.perform(target.name, dry_run=dry_run, method=target.install_method)


def run_audit(host: Host | None = None, force: bool = False, settings: Settings | None = None) -> Report:
    """Run an opportunistic vulnerability audit.

    Only runs if at least one upgrade is actionable (i.e., there is something
    the user can do about a finding), unless ``force=True``.

    Args:
        host: Host instance. Defaults to default_host().
        force: Run audit even if no upgrades are pending.
        settings: When given, supplies the host (dist name, cache dir, logger).

    Returns:
        A Report that may include Vulnerability entries.
    """
    active_host = _host_from(host, settings)
    report = check_for_updates(host=active_host, position="start", allow_network=False, notify_at_exit=False)

    any_actionable = bool(report.host_dist and report.host_dist.actionable) or any(
        dep.actionable for dep in report.dependencies
    )
    if not any_actionable and not force:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: nothing to upgrade, no actionable fix possible",),
            errors=report.errors,
        )

    vulns, tool = run_available_audit()
    if tool is None:
        return Report(
            host_dist=report.host_dist,
            dependencies=report.dependencies,
            notes=("audit skipped: no audit tool available on PATH (pip-audit, safety, uv)",),
            errors=report.errors,
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
        errors=report.errors,
    )


def self_upgrade(host: Host | None = None, dry_run: bool = False, settings: Settings | None = None) -> UpgradeResult:
    """Self-upgrade the host distribution.

    Args:
        host: Host instance. Defaults to default_host().
        dry_run: Print the upgrade command without executing it.
        settings: When given, supplies the host (dist name, cache dir, logger).

    Returns:
        An UpgradeResult describing what happened.
    """
    active_host = _host_from(host, settings)
    return upgrade_module.perform(active_host.dist_name, dry_run=dry_run)


def self_check(host: Host | None = None) -> list[str]:
    """Verify that all installed distributions satisfy their Requires-Dist.

    Args:
        host: Unused; present for API symmetry.

    Returns:
        List of human-readable integrity problem strings. Empty = clean.
    """
    del host
    return integrity_check.run()


def clear_cache(host: Host | None = None, settings: Settings | None = None) -> None:
    """Clear the sidecar cache.

    Args:
        host: Host instance. Defaults to default_host().
        settings: When given, supplies the host (dist name, cache dir, logger).
    """
    active_host = _host_from(host, settings)
    cache = Cache.load(active_host.cache_dir)
    cache.clear()
    cache.save()


def snooze(target: str, days: int, host: Host | None = None, settings: Settings | None = None) -> None:
    """Snooze upgrade notifications for a specific package version.

    Args:
        target: Target identifier, e.g. 'my-app==1.2.3'.
        days: Number of days to snooze.
        host: Host instance. Defaults to default_host().
        settings: When given, supplies the host (dist name, cache dir, logger).
    """
    active_host = _host_from(host, settings)
    cache = Cache.load(active_host.cache_dir)
    cache.snooze(target, days)
    cache.save()


__all__ = [
    "Position",
    "check_for_updates",
    "check_targets",
    "clear_cache",
    "run_audit",
    "self_check",
    "self_upgrade",
    "snooze",
    "upgrade_target",
]
