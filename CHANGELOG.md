# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Support for python39

## [0.0.1] - 2026-07-03

### Added

- Update checking for any installed distribution against PyPI, with PEP 440 version comparison.
- Zero-cost background check for long-running apps: cache read at startup, refresh on a daemon thread, update notice printed at exit.
- Check other apps/packages wherever they are installed: current environment, `uv tool`, pipx, or bare executables on PATH.
- `diu` short CLI alias with subcommands: `check`, `status`, `audit`, `upgrade`, `watch`, `snooze`, `clear-cache`, `integrity-check`.
- Check multiple targets at once: positional names, `--requirements <file>`, or a persistent watch list (`diu watch add/remove/list`, `check --watched`).
- Self-upgrade (and upgrade of other apps) via the detected install method: uv tool, pipx, venv pip, user pip, or system pip.
- Opportunistic vulnerability auditing via `uv audit`, `pip-audit`, or `safety` when present on PATH.
- Integrity check verifying installed distributions satisfy their `Requires-Dist` (PEP 440/508 semantics).
- Prerelease, yanked, and dev-release detection; `--include-prereleases` opt-in.
- Configurable cooloff window suppressing alerts for brand-new releases (default 14 days).
- Per-target snoozes (`diu snooze pkg==1.2.3 --days 30`).
- JSON sidecar cache with configurable TTL, stored in the platform per-user cache directory.
- Script-friendly CLI: `--json` output, `--quiet` mode, and exit codes 0 (up to date), 1 (error), 10 (upgrades available), 11 (fixable vulnerabilities).
- `--dry-run` on every state-changing command.
- Three-line argparse integration for host apps: `add_upgrade_command`, `add_check_command`, `run_if_upgrade_command`, `install_background_check`.
- `Settings` object for programmatic configuration, loadable from `[tool.do_i_need_to_upgrade]` in `pyproject.toml` or a standalone TOML file.
- End-user kill switch honored everywhere: `DO_I_NEED_TO_UPGRADE=off` / `no-network` env var and a per-user config file, always overriding app settings.
- Private package index support via HTTPS `index_url` templates.
- ANSI color output respecting `NO_COLOR`, `CI`, `TERM=dumb`, and TTY detection.
- Vendoring support (relative imports throughout) and a generated single-file, stdlib-only lite build (`diu_lite.py`).
