"""Opportunistic vulnerability audit via uv audit, pip-audit, or safety.

No third-party runtime deps are required. Each audit tool is called as a
subprocess and detected via shutil.which.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from typing import Optional

from .report import Vulnerability

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
        proc = subprocess.run(  # nosec B603
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
        parsed: object = json.loads(text[min(starts) :])
        return parsed
    except json.JSONDecodeError:
        return None


def _parse_pip_audit(stdout: str) -> list[Vulnerability] | None:
    """Parse pip-audit JSON output into Vulnerability records.

    Args:
        stdout: Raw stdout string from pip-audit.

    Returns:
        List of Vulnerability instances, or None if the output is not
        recognizable pip-audit JSON (so the tool must not be treated as
        having run successfully).
    """
    payload = _extract_json(stdout)
    packages: list[dict]  # type: ignore[type-arg]
    if isinstance(payload, list):
        packages = [p for p in payload if isinstance(p, dict)]
    elif isinstance(payload, dict) and isinstance(payload.get("dependencies"), list):
        packages = [p for p in payload["dependencies"] if isinstance(p, dict)]
    else:
        return None
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


def _parse_safety(stdout: str) -> list[Vulnerability] | None:
    """Parse safety JSON output into Vulnerability records.

    Args:
        stdout: Raw stdout string from safety scan.

    Returns:
        List of Vulnerability instances, or None if the output is not
        recognizable safety JSON.
    """
    payload = _extract_json(stdout)
    if not isinstance(payload, dict) or "vulnerabilities" not in payload:
        return None
    vulns = payload.get("vulnerabilities")
    if not isinstance(vulns, list):
        return None
    findings: list[Vulnerability] = []
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


AuditRunner = Callable[[], tuple[list[Vulnerability], Optional[str]]]


def _runner_uv_audit() -> tuple[list[Vulnerability], Optional[str]]:
    """Run uv pip audit and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable or the
        output is not valid audit JSON (e.g. the uv on PATH lacks an audit
        subcommand — a usage error must not be reported as a clean audit).
    """
    if not _which("uv"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["uv", "pip", "audit", "--format", "json"])
    if rc is None:
        return [], None
    findings = _parse_pip_audit(stdout)
    if findings is None:
        return [], None
    return findings, "uv-audit"


def _runner_pip_audit() -> tuple[list[Vulnerability], Optional[str]]:
    """Run pip-audit and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable or the
        output is not valid pip-audit JSON.
    """
    if not _which("pip-audit"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["pip-audit", "--format", "json"])
    findings = _parse_pip_audit(stdout) if rc is not None else None
    if findings is None:
        stdout, _stderr, rc = _run_cmd([sys.executable, "-m", "pip_audit", "--format", "json"])
        findings = _parse_pip_audit(stdout) if rc is not None else None
    if findings is None:
        return [], None
    return findings, "pip-audit"


def _runner_safety() -> tuple[list[Vulnerability], str | None]:
    """Run safety scan and return (vulnerabilities, tool_name_or_None).

    Returns:
        Tuple of findings and tool name, or ([], None) if unavailable or the
        output is not valid safety JSON.
    """
    if not _which("safety"):
        return [], None
    stdout, _stderr, rc = _run_cmd(["safety", "scan", "--output", "json"])
    if rc is None:
        return [], None
    findings = _parse_safety(stdout)
    if findings is None:
        return [], None
    return findings, "safety"


def run_available_audit() -> tuple[list[Vulnerability], Optional[str]]:
    """Run the first available audit tool and return (vulnerabilities, tool_name).

    Tries uv audit first, then pip-audit, then safety. A tool that is on PATH
    but fails to produce recognizable audit JSON is skipped, so the next tool
    still gets a chance to run.

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
