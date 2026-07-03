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

## Installation

```bash
pipx install do_i_need_to_upgrade
```

Or with uv:

```bash
uv tool install do_i_need_to_upgrade
```

## Quickstart

```python
from do_i_need_to_upgrade import check_for_updates, GenericHost

host = GenericHost(dist_name="my-app")  # cache defaults to the per-user cache dir
# Zero-cost background check; notification appears when program exits:
check_for_updates(host=host, position="start")
```

The background check is designed for **long-running applications**: the
refresh runs on a daemon thread, so the process must stay alive a few seconds
for the result to land in the cache. Short-lived CLI apps should use
`position="end"` (refresh after doing their real work) or `"both"`.

## CLI

```bash
do_i_need_to_upgrade --help
do_i_need_to_upgrade check          # synchronous PyPI refresh
do_i_need_to_upgrade status         # show cache without network
do_i_need_to_upgrade audit          # vulnerability scan
do_i_need_to_upgrade upgrade        # self-upgrade
do_i_need_to_upgrade snooze do_i_need_to_upgrade==0.1.0 --days 30
do_i_need_to_upgrade clear-cache
do_i_need_to_upgrade integrity-check
```

Exit codes (script-friendly):

| Code | Meaning |
| ---- | ------- |
| 0    | Up to date / success |
| 1    | Error, or integrity problems found |
| 10   | Upgrades available (`check`) |
| 11   | Vulnerabilities with available fixes (`audit`) |

```bash
do_i_need_to_upgrade check --no-network || echo "time to upgrade"
```

## Contributing

See [CONTRIBUTING.md](docs/extending/CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
