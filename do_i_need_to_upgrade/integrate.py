"""Drop-in integration helpers for host applications.

An app author adds an ``upgrade`` (and optionally ``check-updates``)
subcommand to their existing argparse CLI with three lines::

    subparsers = parser.add_subparsers(dest="command")
    integrate.add_upgrade_command(subparsers, dist_name="my-app")
    ...
    args = parser.parse_args()
    if (rc := integrate.run_if_upgrade_command(args)) is not None:
        sys.exit(rc)

Long-running apps get the zero-cost startup check with one call::

    integrate.install_background_check("my-app")

Everything stored on the argparse Namespace is ``_diu_``-prefixed so it
cannot collide with the host app's own arguments.
"""

from __future__ import annotations

import argparse
import functools
import sys

from . import api
from .report import Report
from .settings import Position, Settings


def _effective_settings(dist_name: str, settings: Settings | None) -> Settings:
    """Return resolved Settings for dist_name.

    Args:
        dist_name: The host distribution name.
        settings: App-supplied settings, or None for defaults.

    Returns:
        Settings with end-user overrides (env var, user config) applied.
    """
    base = settings if settings is not None else Settings(dist_name=dist_name)
    return base.resolve()


def _run_upgrade_command(dist_name: str, settings: Settings | None, args: argparse.Namespace) -> int:
    """Execute the integrated 'upgrade' subcommand.

    Args:
        dist_name: The host distribution name.
        settings: App-supplied settings, or None.
        args: Parsed argparse namespace.

    Returns:
        Process exit code.
    """
    resolved = _effective_settings(dist_name, settings)
    if getattr(args, "_diu_check", False):
        report = api.check_for_updates(
            settings=resolved.replace(position="end" if resolved.allow_network else "start", notify="return-only"),
        )
        text = report.render_text()
        print(text if text else f"{dist_name} is up to date.")
        return 0
    result = api.self_upgrade(settings=resolved, dry_run=getattr(args, "_diu_dry_run", False))
    if result.argv is None:
        print(f"No upgrade path for install method: {result.method.value}", file=sys.stderr)
        return 1
    if not result.attempted:
        print(f"Would run: {' '.join(result.argv)} (method={result.method.value})")
        return 0
    print(f"Ran: {' '.join(result.argv)}")
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return 0 if result.ok else 1


def _run_check_command(dist_name: str, settings: Settings | None, args: argparse.Namespace) -> int:
    """Execute the integrated 'check' subcommand.

    Args:
        dist_name: The host distribution name.
        settings: App-supplied settings, or None.
        args: Parsed argparse namespace.

    Returns:
        0 when up to date, 10 when upgrades are available, 1 on errors.
    """
    resolved = _effective_settings(dist_name, settings)
    if getattr(args, "_diu_no_network", False):
        resolved = resolved.replace(allow_network=False)
    position: Position = "end" if resolved.allow_network else "start"
    report = api.check_for_updates(settings=resolved.replace(position=position, notify="return-only"))
    text = report.render_text()
    print(text if text else f"{dist_name} is up to date.")
    has_upgrades = bool(report.host_dist and report.host_dist.actionable) or any(
        dep.actionable for dep in report.dependencies
    )
    if has_upgrades:
        return 10
    return 1 if report.errors else 0


def add_upgrade_command(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    dist_name: str,
    *,
    command: str = "upgrade",
    settings: Settings | None = None,
) -> None:
    """Register an 'upgrade' subcommand on a host app's parser.

    Args:
        subparsers: The host's ``parser.add_subparsers(...)`` result.
        dist_name: The host distribution name to upgrade.
        command: Subcommand name (default 'upgrade').
        settings: Optional app-level Settings.
    """
    parser = subparsers.add_parser(command, help=f"Upgrade {dist_name} to the latest release")
    parser.add_argument("--check", action="store_true", dest="_diu_check", help="Only report; do not install")
    parser.add_argument(
        "--dry-run", action="store_true", dest="_diu_dry_run", help="Print the upgrade command, do not run it"
    )
    parser.set_defaults(_diu_func=functools.partial(_run_upgrade_command, dist_name, settings))


def add_check_command(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    dist_name: str,
    *,
    command: str = "check-updates",
    settings: Settings | None = None,
) -> None:
    """Register a 'check-updates' subcommand on a host app's parser.

    Args:
        subparsers: The host's ``parser.add_subparsers(...)`` result.
        dist_name: The host distribution name to check.
        command: Subcommand name (default 'check-updates').
        settings: Optional app-level Settings.
    """
    parser = subparsers.add_parser(command, help=f"Check whether {dist_name} has upgrades available")
    parser.add_argument(
        "--no-network", action="store_true", dest="_diu_no_network", help="Use cache only, no PyPI fetches"
    )
    parser.set_defaults(_diu_func=functools.partial(_run_check_command, dist_name, settings))


def run_if_upgrade_command(args: argparse.Namespace) -> int | None:
    """Dispatch an integrated subcommand if the parsed args selected one.

    Call this from the host's main() after parse_args(); a non-None return
    is the exit code of the integrated command, None means "not ours".

    Args:
        args: The parsed argparse namespace.

    Returns:
        Exit code if an integrated subcommand ran, otherwise None.
    """
    func = getattr(args, "_diu_func", None)
    if func is None:
        return None
    result: int = func(args)
    return result


def install_background_check(dist_name: str, settings: Settings | None = None) -> Report | None:
    """One-liner startup check for long-running applications.

    Reads the cache in the foreground (no blocking I/O), schedules a
    background PyPI refresh, and — unless configured otherwise — prints an
    update notice to stderr when the process exits. Honors the end-user kill
    switch (``DO_I_NEED_TO_UPGRADE=off`` and the user config file).

    Args:
        dist_name: The host distribution name.
        settings: Optional app-level Settings; ``notify`` defaults to
            'exit-message' when this is None.

    Returns:
        The cache-backed Report, or None when checking is disabled.
    """
    base = settings if settings is not None else Settings(dist_name=dist_name, notify="exit-message")
    resolved = base.resolve()
    if resolved.position == "off":
        return None
    return api.check_for_updates(settings=resolved.replace(position="start"))


__all__ = [
    "add_check_command",
    "add_upgrade_command",
    "install_background_check",
    "run_if_upgrade_command",
]
