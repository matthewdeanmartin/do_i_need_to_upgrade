# do_i_need_to_upgrade

A drop-in Python library that gives any CLI application zero-cost background
update checking, vulnerability auditing, and self-upgrade capabilities.

## Features

- **Stdlib-only PyPI client** — no httpx, no requests, no urllib3
- **Background check** — daemon thread + atexit notification (zero cost to startup)
- **JSON sidecar cache** with configurable TTL and per-package snooze support
- **14-day cooloff window** — suppresses alerts for brand-new releases
- **Prerelease & yanked version detection**
- **Vulnerability auditing** — uses `uv audit`, `pip-audit`, or `safety` opportunistically
- **Self-upgrade** — detects install method (uv tool / pipx / venv pip) and runs the right command
- **Color ANSI output** — respects `NO_COLOR`, `CI`, `TERM=dumb`, and TTY
- **Generic Host protocol** — drop it into any app with two lines
