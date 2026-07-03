"""Tests for the report module."""

from __future__ import annotations

from do_i_need_to_upgrade.report import Report, VersionInfo, Vulnerability


def _make_vi(
    name: str = "mypkg",
    installed: str = "1.0",
    latest: str | None = "2.0",
    upgrade: bool = True,
    cooloff: bool = False,
    yanked: bool = False,
    is_dev: bool = False,
) -> VersionInfo:
    return VersionInfo(
        name=name,
        installed=installed,
        latest=latest,
        latest_published=None,
        age_days=100.0,
        is_upgrade_available=upgrade,
        is_in_cooloff=cooloff,
        is_yanked=yanked,
        is_dev=is_dev,
    )


def test_version_info_actionable() -> None:
    """Actionable upgrade."""
    vi = _make_vi()
    assert vi.actionable


def test_version_info_not_actionable_no_upgrade() -> None:
    """No upgrade available means not actionable."""
    vi = _make_vi(upgrade=False)
    assert not vi.actionable


def test_version_info_not_actionable_cooloff() -> None:
    """Cooloff suppresses actionable."""
    vi = _make_vi(cooloff=True)
    assert not vi.actionable


def test_version_info_not_actionable_yanked() -> None:
    """Yanked suppresses actionable."""
    vi = _make_vi(yanked=True)
    assert not vi.actionable


def test_version_info_not_actionable_dev() -> None:
    """Dev release suppresses actionable."""
    vi = _make_vi(is_dev=True)
    assert not vi.actionable


def test_report_is_empty_when_no_actions() -> None:
    """Empty report when nothing actionable."""
    report = Report()
    assert report.is_empty


def test_report_not_empty_with_actionable_host() -> None:
    """Report is not empty when host has actionable upgrade."""
    report = Report(host_dist=_make_vi())
    assert not report.is_empty


def test_report_render_text_upgrade() -> None:
    """Render text includes upgrade line."""
    report = Report(host_dist=_make_vi())
    text = report.render_text()
    assert "mypkg" in text
    assert "2.0" in text


def test_report_render_text_no_update() -> None:
    """Render text for up-to-date is empty."""
    report = Report(host_dist=_make_vi(upgrade=False))
    text = report.render_text()
    assert text == ""


def test_vulnerability_actionable() -> None:
    """Vulnerability is actionable when fix_versions is non-empty."""
    vuln = Vulnerability(
        name="pkg",
        installed="1.0",
        advisory_id="CVE-2024-0001",
        severity="high",
        fix_versions=("1.1",),
        source="pip-audit",
    )
    assert vuln.actionable


def test_vulnerability_not_actionable_no_fix() -> None:
    """Vulnerability without fix versions is not actionable."""
    vuln = Vulnerability(
        name="pkg",
        installed="1.0",
        advisory_id="CVE-2024-0001",
        severity="high",
        fix_versions=(),
        source="pip-audit",
    )
    assert not vuln.actionable


def test_report_render_vuln() -> None:
    """Render text includes vulnerability info."""
    vuln = Vulnerability(
        name="pkg",
        installed="1.0",
        advisory_id="CVE-2024-0001",
        severity="high",
        fix_versions=("1.1",),
        source="pip-audit",
    )
    report = Report(vulnerabilities=(vuln,))
    text = report.render_text()
    assert "CVE-2024-0001" in text
