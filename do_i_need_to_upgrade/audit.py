"""Opportunistic vulnerability audit via uv audit, pip-audit, or safety.

No third-party runtime deps are required. Each audit tool is called as a
subprocess and detected via shutil.which.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable

from do_i_need_to_upgrade.report import Vulnerability

AUDIT_TIMEOUT = 60


def _which(tool: str) -> str | None:
    """Return the full path of tool, or None if not on PATH.

    Args:
        tool: Command name to search.

    Returns:
        Full path string or None.
    """
    return shutil.which(tool)


def _run_cmd(argv: list[str]) -> tuple[str, str, int | None]:
    """Run a command and return (stdout, stderr, returncode).

    Args:
        argv: Command argument list.

    Returns:
        Tuple of (stdout, stderr, returncode). returncode is None on failure.
    """
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=AUDIT_TIMEOUT,
            check=False,
        )
        return proc.stdout, proc.stderr, proc.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "", "", None


def _extract_json(text: str) -> object | None:
    """Extract the first JSON value from a string.

    Args:
        text: String that may contain JSON.

    Returns:
        Parsed JSON object or None.
    """
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return None
    try:
        return json.loads(text[min(starts):])
    except json.JSONDecodeError:
        return None


def _parse_pip_audit(stdout: str) -> list[Vulnerability]:
    """Parse pip-audit JSON output into Vulnerability records.

    Args:
        stdout: Raw stdout string from pip-audit.

    Returns:
        List of Vulnerability instances.
    """
    payload = _extract_json(stdout)
    if payload is None:
        return []
    packages: list[dict]  # type: ignore[type-arg]
    if isinstance(payload, list):
        packages = [p for p in payload if isinstance(p, dict)]
    elif isinstance(payload, dict):
        packages = [p for p in payload.get("dependencies", []) if isinstance(p, dict)]
    else:
        return []
    findings: list[Vulnerability] = []
    for pkg in packages:
        name = str(pkg.get("name", ""))
        version = str(pkg.get("version", ""))
        for vuln in pkg.get("vulns", []) or []:
            if not isinstance(vuln, dict):
                continue
            findings.append(
                Vulnerability(
                    name=name,
                    installed=version,
                    advisory_id=str(vuln.get("id", "")),
                    severity=(str(vuln["severity"]).lower() if vuln.get("severity") else None),
                    fix_versions=tuple(str(v) for v in vuln.get("fix_versions") or ()),
                    source="pip-audit",
                )
            )
    return findings


def _parse_safety(stdout: str) -> list[Vulnerability]:
    """Parse safety JSON output into Vulnerability records.

    Args:
        stdout: Raw stdout string from safety scan.

    Returns:
        List of Vulnerability instances.
    """
    payload = _extract_json(stdout)
    if not isinstance(payload, dict):
        return []
    vulns = payload.get("vulnerabilities") or []
    findings: list[Vulnerability] = []
    if isinstance(vulns, list):
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            findings.append(
                Vulnerability(
                    name=str(vuln.get("package_name", "")),
                    installed=str(vuln.get("analyzed_version", "")),
                    advisory_id=str(vuln.get("vulnerability_id", "")),
                    severity=(str(vuln["severity"]).lower() if vuln.get("severity") else None),
                    fix_versions=tuple(str(v) for v in vuln.get("fixed_versions") or ()),
                    source="safety",
                )
            )
    return findings


AuditRunner = Callable[[], tuple[list[Vulnerability], str | None]]


def _runner_uv_audit() -> tuple[list[Vulnerability], str | None]:
    """Run uv pip audit and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable.
    """
    if not _which("uv"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["uv", "pip", "audit", "--format", "json"])
    if rc is None:
        return [], None
    return _parse_pip_audit(stdout), "uv-audit"


def _runner_pip_audit() -> tuple[list[Vulnerability], str | None]:
    """Run pip-audit and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable.
    """
    if not _which("pip-audit"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["pip-audit", "--format", "json"])
    if rc is None:
        stdout, _stderr, rc = _run_cmd([sys.executable, "-m", "pip_audit", "--format", "json"])
    if rc is None:
        return [], None
    return _parse_pip_audit(stdout), "pip-audit"


def _runner_safety() -> tuple[list[Vulnerability], str | None]:
    """Run safety scan and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable.
    """
    if not _which("safety"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["safety", "scan", "--output", "json"])
    if rc is None:
        return [], None
    return _parse_safety(stdout), "safety"


def run_available_audit() -> tuple[list[Vulnerability], str | None]:
    """Run the first available audit tool and return (vulnerabilities, tool_name).

    Tries uv audit first, then pip-audit, then safety.

    Returns:
        Tuple of Vulnerability list and the tool name used, or ([], None) if
        no audit tool is available on PATH.
    """
    for runner in (_runner_uv_audit, _runner_pip_audit, _runner_safety):
        vulns, tool = runner()
        if tool is not None:
            return vulns, tool
    return [], None


__all__ = ["run_available_audit"]
