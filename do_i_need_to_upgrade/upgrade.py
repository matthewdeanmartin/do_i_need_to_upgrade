"""Self-upgrade dispatcher.

Detects how the host distribution was installed and runs the appropriate
upgrade command.
"""

from __future__ import annotations

import subprocess  # nosec B404
from dataclasses import dataclass

from .install_method import InstallMethod, detect, upgrade_argv

UPGRADE_TIMEOUT = 300


@dataclass(frozen=True)
class UpgradeResult:
    """Result of a self-upgrade attempt."""

    method: InstallMethod
    argv: list[str] | None
    returncode: int | None
    stdout: str
    stderr: str
    attempted: bool

    @property
    def ok(self) -> bool:
        """Return True if the upgrade was attempted and succeeded.

        Returns:
            True when returncode is 0 and the upgrade was attempted.
        """
        return self.attempted and self.returncode == 0


def perform(dist_name: str, dry_run: bool = False, method: InstallMethod | None = None) -> UpgradeResult:
    """Detect install method and perform (or simulate) an upgrade.

    Args:
        dist_name: The distribution name to upgrade.
        dry_run: If True, detect and return the command without running it.
        method: Known install method (e.g. from a resolver); detected from
            the current environment when None.

    Returns:
        An UpgradeResult describing what happened.
    """
    if method is None:
        method = detect(dist_name)
    argv = upgrade_argv(method, dist_name)
    if argv is None or method == InstallMethod.EDITABLE:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr="", attempted=False)
    if dry_run:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr="", attempted=False)
    try:
        proc = subprocess.run(  # nosec B603
            argv,
            capture_output=True,
            text=True,
            timeout=UPGRADE_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return UpgradeResult(method=method, argv=argv, returncode=None, stdout="", stderr=str(exc), attempted=True)
    return UpgradeResult(
        method=method, argv=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr, attempted=True
    )


__all__ = ["UpgradeResult", "perform"]
