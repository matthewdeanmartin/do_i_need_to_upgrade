"""Command-line entry point for do_i_need_to_upgrade."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal

from . import api, resolvers
from .__about__ import __version__
from .cache import Cache
from .host import GenericHost, Host, default_host
from .install_method import InstallMethod
from .report import Report


def _json_default(value: object) -> object:
    """JSON serializer for types not handled by the default encoder.

    Args:
        value: The value to serialize.

    Returns:
        A JSON-serializable representation.

    Raises:
        TypeError: If the type is not serializable.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _dump_report(report: Report, as_json: bool) -> None:
    """Print a Report as text or JSON.

    Args:
        report: The Report to render.
        as_json: If True, output JSON; otherwise plain text.
    """
    if as_json:
        print(json.dumps(dataclasses.asdict(report), default=_json_default, indent=2))
        return
    text = report.render_text()
    if text:
        print(text)
    else:
        print("No upgrades or vulnerabilities to report.")


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UPGRADES_AVAILABLE = 10
EXIT_VULNERABILITIES = 11

_EXIT_CODE_HELP = (
    "exit codes: 0 = up to date / success, 1 = error or integrity problems, "
    "10 = upgrades available, 11 = vulnerabilities with available fixes"
)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Shared options live on a parent parser so they are accepted both before
    and after the subcommand (e.g. both `--json check` and `check --json`).

    Returns:
        Configured ArgumentParser.
    """
    # default=SUPPRESS so the attribute is only set when the flag is given.
    # Subparsers parse into a fresh namespace and copy it over the root one,
    # so a plain default here would clobber a flag given before the
    # subcommand (e.g. `--cache-dir X check`). Read these via getattr.
    suppress = argparse.SUPPRESS
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dist", default=suppress, help="Distribution name to check (default: do_i_need_to_upgrade)")
    common.add_argument("--cache-dir", default=suppress, dest="cache_dir", help="Override cache directory")
    common.add_argument("--json", action="store_true", default=suppress, help="Emit JSON output")
    common.add_argument(
        "--no-network", action="store_true", default=suppress, dest="no_network", help="Use cache only, no PyPI fetches"
    )
    common.add_argument(
        "--include-prereleases",
        action="store_true",
        default=suppress,
        dest="include_prereleases",
        help="Include pre-release versions",
    )
    common.add_argument(
        "--quiet", action="store_true", default=suppress, help="Print nothing; communicate via exit code only"
    )

    parser = argparse.ArgumentParser(
        prog="do_i_need_to_upgrade",
        description="Drop-in application self-upgrade checker and vulnerability auditor.",
        epilog=_EXIT_CODE_HELP,
        parents=[common],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("status", help="Show cached state (no network, no subprocess)", parents=[common])

    check_parser = subparsers.add_parser(
        "check",
        help="Check given packages for upgrades (default: self + direct deps)",
        parents=[common],
    )
    check_parser.add_argument(
        "names", nargs="*", help="Packages/apps to check, wherever installed (env, uv tool, pipx, PATH)"
    )
    check_parser.add_argument("--watched", action="store_true", help="Also check everything on the watch list")
    check_parser.add_argument(
        "--requirements", "-r", default=None, dest="requirements", help="Also check every name in a requirements file"
    )

    audit_parser = subparsers.add_parser(
        "audit", help="Run vulnerability audit (if tool is installed)", parents=[common]
    )
    audit_parser.add_argument("--force", action="store_true", help="Audit even if no upgrades are pending")

    upgrade_parser = subparsers.add_parser(
        "upgrade", help="Upgrade a package via its detected install method (default: self)", parents=[common]
    )
    upgrade_parser.add_argument("name", nargs="?", default=None, help="Package/app to upgrade (default: self)")
    upgrade_parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Print the argv, do not run")

    watch_parser = subparsers.add_parser("watch", help="Manage the persistent watch list", parents=[common])
    watch_sub = watch_parser.add_subparsers(dest="watch_action", required=True)
    watch_add = watch_sub.add_parser("add", help="Add packages to the watch list", parents=[common])
    watch_add.add_argument("names", nargs="+", help="Package names to watch")
    watch_add.add_argument("--dry-run", action="store_true", dest="dry_run", help="Show what would change, do not save")
    watch_remove = watch_sub.add_parser("remove", help="Remove packages from the watch list", parents=[common])
    watch_remove.add_argument("names", nargs="+", help="Package names to stop watching")
    watch_remove.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="Show what would change, do not save"
    )
    watch_sub.add_parser("list", help="Show the watch list", parents=[common])

    subparsers.add_parser("integrity-check", help="Verify installed dists satisfy Requires-Dist", parents=[common])
    clear_parser = subparsers.add_parser("clear-cache", help="Delete the sidecar cache", parents=[common])
    clear_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="Show what would be cleared, do not clear"
    )

    snooze_parser = subparsers.add_parser("snooze", help="Snooze a specific upgrade suggestion", parents=[common])
    snooze_parser.add_argument("target", help="e.g. package==1.2.3")
    snooze_parser.add_argument("--days", type=int, default=14, help="Snooze duration in days (default: 14)")
    snooze_parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Show the snooze, do not save")

    return parser


def _make_host(dist_name: str | None, cache_dir_str: str | None) -> Host:
    """Construct a Host from CLI arguments.

    Args:
        dist_name: Distribution name or None for default.
        cache_dir_str: Cache directory path string or None for default.

    Returns:
        A Host instance.
    """
    name = dist_name or "do_i_need_to_upgrade"
    if cache_dir_str:
        return GenericHost(dist_name=name, cache_dir=Path(cache_dir_str))
    return default_host(name)


def _cmd_status(host: Host, as_json: bool) -> int:
    """Handle the 'status' subcommand.

    Args:
        host: The Host instance.
        as_json: Whether to emit JSON output.

    Returns:
        Exit code.
    """
    cache = Cache.load(host.cache_dir)
    if as_json:
        print(json.dumps(cache.data, indent=2, sort_keys=True))
        return 0
    pypi_entries = cache.data.get("pypi", {})
    print(f"Cache: {cache.path}")
    print(f"Tracked packages: {len(pypi_entries)}")
    for name, entry in sorted(pypi_entries.items()):
        pre = " [prerelease]" if entry.get("is_prerelease") else ""
        yank = " [YANKED]" if entry.get("is_yanked") else ""
        print(f"  {name}: latest={entry.get('latest')}{pre}{yank} published={entry.get('published')}")
    audit_summary = cache.data.get("audit_summary")
    if audit_summary:
        print(f"Last audit: {cache.data.get('last_audit_utc')} {audit_summary}")
    snoozes = cache.data.get("suppressed_until", {})
    if snoozes:
        print(f"Snoozes: {snoozes}")
    return 0


def _report_exit_code(report: Report, missing_targets: bool = False) -> int:
    """Map a Report to the script-friendly exit-code contract.

    Args:
        report: The Report to inspect.
        missing_targets: True if any requested target was not installed.

    Returns:
        EXIT_UPGRADES_AVAILABLE if actionable upgrades exist, EXIT_ERROR on
        errors or missing targets, EXIT_OK otherwise.
    """
    has_upgrades = bool(report.host_dist and report.host_dist.actionable) or any(
        dep.actionable for dep in report.dependencies
    )
    if has_upgrades:
        return EXIT_UPGRADES_AVAILABLE
    if report.errors or missing_targets:
        return EXIT_ERROR
    return EXIT_OK


def _gather_check_names(host: Host, names: list[str], watched: bool, requirements: str | None) -> list[str]:
    """Combine explicit names, the watch list, and a requirements file.

    Args:
        host: The Host instance (supplies the cache holding the watch list).
        names: Names given on the command line.
        watched: Whether to include the persisted watch list.
        requirements: Optional path to a requirements file.

    Returns:
        Combined list of names (may contain duplicates; resolver dedupes).

    Raises:
        FileNotFoundError: If the requirements file does not exist.
    """
    combined = list(names)
    if watched:
        combined.extend(Cache.load(host.cache_dir).watch_list())
    if requirements:
        combined.extend(resolvers.parse_requirements_file(Path(requirements)))
    return combined


def _cmd_check(
    host: Host,
    as_json: bool,
    no_network: bool,
    include_prereleases: bool,
    quiet: bool,
    names: list[str],
    watched: bool,
    requirements: str | None,
) -> int:
    """Handle the 'check' subcommand.

    With no targets, checks the host distribution and its direct deps (the
    original self-check). With targets (positional names, --watched, or
    --requirements), checks exactly those wherever they are installed.

    Args:
        host: The Host instance.
        as_json: Whether to emit JSON output.
        no_network: Skip network calls.
        include_prereleases: Include pre-releases.
        quiet: Print nothing; exit code only.
        names: Positional package names to check.
        watched: Include the persisted watch list.
        requirements: Optional requirements file whose names are checked.

    Returns:
        EXIT_UPGRADES_AVAILABLE if actionable upgrades exist, EXIT_ERROR on
        errors or targets that are not installed, EXIT_OK otherwise.
    """
    try:
        all_names = _gather_check_names(host, names, watched, requirements)
    except FileNotFoundError as exc:
        if not quiet:
            print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if all_names:
        targets = resolvers.resolve_all(all_names)
        report = api.check_targets(
            targets,
            host=host,
            allow_network=not no_network,
            include_prereleases=include_prereleases,
        )
        if not quiet:
            _dump_report(report, as_json=as_json)
        missing = any(t.installed_version is None for t in targets)
        return _report_exit_code(report, missing_targets=missing)

    position: Literal["start", "end"] = "start" if no_network else "end"
    report = api.check_for_updates(
        host=host,
        position=position,
        allow_network=not no_network,
        include_prereleases=include_prereleases,
        notify_at_exit=False,
    )
    if not quiet:
        _dump_report(report, as_json=as_json)
    return _report_exit_code(report)


def _cmd_audit(host: Host, as_json: bool, force: bool, quiet: bool = False) -> int:
    """Handle the 'audit' subcommand.

    Args:
        host: The Host instance.
        as_json: Whether to emit JSON output.
        force: Force audit even when nothing actionable.
        quiet: Print nothing; exit code only.

    Returns:
        EXIT_VULNERABILITIES if actionable vulnerabilities found, EXIT_OK otherwise.
    """
    report = api.run_audit(host=host, force=force)
    if not quiet:
        _dump_report(report, as_json=as_json)
    return EXIT_VULNERABILITIES if any(v.actionable for v in report.vulnerabilities) else EXIT_OK


def _cmd_upgrade(host: Host, dry_run: bool, as_json: bool, name: str | None = None) -> int:
    """Handle the 'upgrade' subcommand.

    Args:
        host: The Host instance.
        dry_run: Only print the upgrade command.
        as_json: Whether to emit JSON output.
        name: Package to upgrade; None means self-upgrade of the host dist.

    Returns:
        Exit code.
    """
    if name is not None:
        target = resolvers.resolve(name)
        if target.installed_version is None or target.install_method == InstallMethod.UNKNOWN:
            where = "not installed" if target.source == "none" else f"found via {target.source}"
            print(f"Cannot upgrade {name}: {where}, no known upgrade method.", file=sys.stderr)
            return EXIT_ERROR
        result = api.upgrade_target(target, dry_run=dry_run)
    else:
        result = api.self_upgrade(host=host, dry_run=dry_run)
    if as_json:
        print(
            json.dumps(
                {
                    "method": result.method.value,
                    "argv": result.argv,
                    "returncode": result.returncode,
                    "attempted": result.attempted,
                    "ok": result.ok,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                indent=2,
            )
        )
        return 0 if result.ok or dry_run else 1
    if result.argv is None:
        print(f"No upgrade path for install method: {result.method.value}")
        return 1
    if dry_run or not result.attempted:
        print(f"Would run: {' '.join(result.argv)} (method={result.method.value})")
        return 0
    print(f"Ran: {' '.join(result.argv)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 0 if result.ok else 1


def _cmd_integrity_check(as_json: bool) -> int:
    """Handle the 'integrity-check' subcommand.

    Args:
        as_json: Whether to emit JSON output.

    Returns:
        1 if problems found, 0 otherwise.
    """
    problems = api.self_check()
    if as_json:
        print(json.dumps({"problems": problems}, indent=2))
    else:
        if not problems:
            print("OK: all installed distributions satisfy their Requires-Dist.")
        else:
            print(f"Found {len(problems)} integrity problem(s):")
            for problem in problems:
                print(f"  - {problem}")
    return 0 if not problems else 1


def _cmd_clear_cache(host: Host, dry_run: bool = False) -> int:
    """Handle the 'clear-cache' subcommand.

    Args:
        host: The Host instance.
        dry_run: Report what would be cleared without clearing.

    Returns:
        Exit code (always 0).
    """
    if dry_run:
        cache = Cache.load(host.cache_dir)
        print(f"Would clear cache at {cache.path}")
        return EXIT_OK
    api.clear_cache(host=host)
    print("Cache cleared.")
    return EXIT_OK


def _cmd_watch(host: Host, action: str, names: list[str], as_json: bool, dry_run: bool = False) -> int:
    """Handle the 'watch' subcommand (add/remove/list).

    Args:
        host: The Host instance.
        action: One of 'add', 'remove', 'list'.
        names: Package names for add/remove.
        as_json: Whether to emit JSON output.
        dry_run: Report what would change without saving.

    Returns:
        Exit code (always 0).
    """
    cache = Cache.load(host.cache_dir)
    if action == "add":
        for name in names:
            added = cache.watch_add(name)
            verb = "Would watch" if dry_run else "Watching"
            print(f"{verb} {name}." if added else f"{name} is already watched.")
        if not dry_run:
            cache.save()
    elif action == "remove":
        for name in names:
            removed = cache.watch_remove(name)
            verb = "Would stop watching" if dry_run else "Stopped watching"
            print(f"{verb} {name}." if removed else f"{name} was not watched.")
        if not dry_run:
            cache.save()
    else:
        watched = cache.watch_list()
        if as_json:
            print(json.dumps({"watch": watched}, indent=2))
        elif watched:
            for name in watched:
                print(name)
        else:
            print("Watch list is empty.")
    return EXIT_OK


def _cmd_snooze(host: Host, target: str, days: int, dry_run: bool = False) -> int:
    """Handle the 'snooze' subcommand.

    Args:
        host: The Host instance.
        target: Target identifier to snooze.
        days: Number of days to snooze.
        dry_run: Report the snooze without saving it.

    Returns:
        Exit code (always 0).
    """
    if dry_run:
        print(f"Would snooze {target} for {days} day(s).")
        return EXIT_OK
    api.snooze(target=target, days=days, host=host)
    print(f"Snoozed {target} for {days} day(s).")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for the CLI.

    Args:
        argv: Argument list. Defaults to sys.argv[1:].

    Returns:
        Exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    host = _make_host(getattr(args, "dist", None), getattr(args, "cache_dir", None))
    command = args.command or "check"
    as_json = getattr(args, "json", False)
    quiet = getattr(args, "quiet", False)

    result: int
    if command == "status":
        result = _cmd_status(host, as_json=as_json)
    elif command == "check":
        result = _cmd_check(
            host,
            as_json=as_json,
            no_network=getattr(args, "no_network", False),
            include_prereleases=getattr(args, "include_prereleases", False),
            quiet=quiet,
            names=getattr(args, "names", []),
            watched=getattr(args, "watched", False),
            requirements=getattr(args, "requirements", None),
        )
    elif command == "audit":
        result = _cmd_audit(host, as_json=as_json, force=getattr(args, "force", False), quiet=quiet)
    elif command == "upgrade":
        result = _cmd_upgrade(
            host,
            dry_run=getattr(args, "dry_run", False),
            as_json=as_json,
            name=getattr(args, "name", None),
        )
    elif command == "watch":
        result = _cmd_watch(
            host,
            action=args.watch_action,
            names=getattr(args, "names", []),
            as_json=as_json,
            dry_run=getattr(args, "dry_run", False),
        )
    elif command == "integrity-check":
        result = _cmd_integrity_check(as_json=as_json)
    elif command == "clear-cache":
        result = _cmd_clear_cache(host, dry_run=getattr(args, "dry_run", False))
    elif command == "snooze":
        result = _cmd_snooze(host, target=args.target, days=args.days, dry_run=getattr(args, "dry_run", False))
    else:
        parser.print_help()
        result = 2
    return result


if __name__ == "__main__":
    sys.exit(main())
