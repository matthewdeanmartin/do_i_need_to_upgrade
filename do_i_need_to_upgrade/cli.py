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

from do_i_need_to_upgrade import api
from do_i_need_to_upgrade.__about__ import __version__
from do_i_need_to_upgrade.cache import Cache
from do_i_need_to_upgrade.host import GenericHost, Host, default_host


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
        return dataclasses.asdict(value)  # type: ignore[call-overload]
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _dump_report(report: api.Report, as_json: bool) -> None:
    """Print a Report as text or JSON.

    Args:
        report: The Report to render.
        as_json: If True, output JSON; otherwise plain text.
    """
    if as_json:
        print(json.dumps(dataclasses.asdict(report), default=_json_default, indent=2))  # type: ignore[call-overload]
        return
    text = report.render_text()
    if text:
        print(text)
    else:
        print("No upgrades or vulnerabilities to report.")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="do_i_need_to_upgrade",
        description="Drop-in application self-upgrade checker and vulnerability auditor.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--dist", default=None, help="Distribution name to check (default: do_i_need_to_upgrade)")
    parser.add_argument("--cache-dir", default=None, dest="cache_dir", help="Override cache directory")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--no-network", action="store_true", dest="no_network", help="Use cache only, no PyPI fetches")
    parser.add_argument(
        "--include-prereleases", action="store_true", dest="include_prereleases", help="Include pre-release versions"
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    subparsers.add_parser("status", help="Show cached state (no network, no subprocess)")
    subparsers.add_parser("check", help="Refresh update info for host + direct deps")
    audit_parser = subparsers.add_parser("audit", help="Run vulnerability audit (if tool is installed)")
    audit_parser.add_argument("--force", action="store_true", help="Audit even if no upgrades are pending")

    upgrade_parser = subparsers.add_parser("upgrade", help="Self-upgrade via detected install method")
    upgrade_parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Print the argv, do not run")

    subparsers.add_parser("integrity-check", help="Verify installed dists satisfy Requires-Dist")
    subparsers.add_parser("clear-cache", help="Delete the sidecar cache")

    snooze_parser = subparsers.add_parser("snooze", help="Snooze a specific upgrade suggestion")
    snooze_parser.add_argument("target", help="e.g. package==1.2.3")
    snooze_parser.add_argument("--days", type=int, default=14, help="Snooze duration in days (default: 14)")

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


def _cmd_check(host: Host, as_json: bool, no_network: bool, include_prereleases: bool) -> int:
    """Handle the 'check' subcommand.

    Args:
        host: The Host instance.
        as_json: Whether to emit JSON output.
        no_network: Skip network calls.
        include_prereleases: Include pre-releases.

    Returns:
        Exit code.
    """
    position: Literal["start", "end"] = "start" if no_network else "end"
    report = api.check_for_updates(
        host=host,
        position=position,
        allow_network=not no_network,
        include_prereleases=include_prereleases,
    )
    _dump_report(report, as_json=as_json)
    return 0


def _cmd_audit(host: Host, as_json: bool, force: bool) -> int:
    """Handle the 'audit' subcommand.

    Args:
        host: The Host instance.
        as_json: Whether to emit JSON output.
        force: Force audit even when nothing actionable.

    Returns:
        1 if actionable vulnerabilities found, 0 otherwise.
    """
    report = api.run_audit(host=host, force=force)
    _dump_report(report, as_json=as_json)
    return 0 if not any(v.actionable for v in report.vulnerabilities) else 1


def _cmd_upgrade(host: Host, dry_run: bool, as_json: bool) -> int:
    """Handle the 'upgrade' subcommand.

    Args:
        host: The Host instance.
        dry_run: Only print the upgrade command.
        as_json: Whether to emit JSON output.

    Returns:
        Exit code.
    """
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


def _cmd_clear_cache(host: Host) -> int:
    """Handle the 'clear-cache' subcommand.

    Args:
        host: The Host instance.

    Returns:
        Exit code (always 0).
    """
    api.clear_cache(host=host)
    print("Cache cleared.")
    return 0


def _cmd_snooze(host: Host, target: str, days: int) -> int:
    """Handle the 'snooze' subcommand.

    Args:
        host: The Host instance.
        target: Target identifier to snooze.
        days: Number of days to snooze.

    Returns:
        Exit code (always 0).
    """
    api.snooze(target=target, days=days, host=host)
    print(f"Snoozed {target} for {days} day(s).")
    return 0


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

    if command == "status":
        return _cmd_status(host, as_json=args.json)
    if command == "check":
        return _cmd_check(
            host,
            as_json=args.json,
            no_network=args.no_network,
            include_prereleases=args.include_prereleases,
        )
    if command == "audit":
        return _cmd_audit(host, as_json=args.json, force=getattr(args, "force", False))
    if command == "upgrade":
        return _cmd_upgrade(host, dry_run=getattr(args, "dry_run", False), as_json=args.json)
    if command == "integrity-check":
        return _cmd_integrity_check(as_json=args.json)
    if command == "clear-cache":
        return _cmd_clear_cache(host)
    if command == "snooze":
        return _cmd_snooze(host, target=args.target, days=args.days)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
