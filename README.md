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

## Integrating into your app

Add a `my-app upgrade` subcommand to an existing argparse CLI in three lines:

```python
import sys
import do_i_need_to_upgrade as diu

subparsers = parser.add_subparsers(dest="command")
diu.add_upgrade_command(subparsers, dist_name="my-app")   # adds `my-app upgrade`
# ... your own subcommands ...
args = parser.parse_args()
if (rc := diu.run_if_upgrade_command(args)) is not None:
    sys.exit(rc)
```

`diu.add_check_command(...)` adds a `check-updates` subcommand the same way.
For long-running apps, the whole feature is one line at startup:

```python
diu.install_background_check("my-app")  # cached check + exit notification
```

Behavior is configured with a `Settings` object, or shipped as defaults in
your `pyproject.toml`:

```toml
[tool.do_i_need_to_upgrade]
position = "start"          # start | end | both | off
notify = "exit-message"     # exit-message | return-only
cooloff_days = 7
check_ttl_hours = 24
check_dependencies = false
index_url = "https://pypi.example.com/pypi/{name}/json"  # private index (https only)
```

Load with `Settings.from_pyproject("my-app")` (dev) or
`Settings.from_toml(path, "my-app")` (e.g. package data shipped in your wheel),
and pass `settings=` to any API function or the integrate helpers.

### No dependency? Vendor it

Prefer not to add a dependency? Two supported paths
(see [docs/usage/vendoring.md](docs/usage/vendoring.md)):

- **Vendor the full package** — internal imports are relative, so copying
  `do_i_need_to_upgrade/` into `yourapp/_vendor/` just works (needs
  `packaging`, which you almost certainly already have).
- **`diu_lite.py`** — a generated, stdlib-only, single-file build
  (`make build-lite`) exposing exactly one function:
  `check_for_updates("your-dist") -> str | None`. Zero dependencies, MIT,
  ~350 lines, honors the same kill switch.

### End-user kill switch

Apps embedding this library phone home to PyPI, so end users always get the
last word, regardless of app settings:

- `DO_I_NEED_TO_UPGRADE=off` — disable checks entirely
- `DO_I_NEED_TO_UPGRADE=no-network` — cache only, no fetches
- `~/.config/do_i_need_to_upgrade.toml` (or `%APPDATA%\do_i_need_to_upgrade.toml`):
  `disabled = true`, `no_network = true`, or `disabled_for = ["some-app"]`

Precedence: environment variable > user config file > app settings > defaults.
(On Python 3.10 the TOML config files are ignored — `tomllib` is stdlib from
3.11; programmatic `Settings` work everywhere.)

## CLI

`diu` is a short alias for `do_i_need_to_upgrade` — same command.

```bash
diu --help
diu check                      # self-check: this dist + direct deps
diu check ruff black yt-dlp    # check other apps, wherever installed
                               # (current env, uv tool, pipx, or PATH)
diu check -r requirements.txt  # check everything in a requirements file
diu watch add yt-dlp           # persist names to a watch list
diu check --watched            # check the whole watch list
diu check --watched --quiet    # exit code only — cron/prompt friendly
diu upgrade                    # self-upgrade via detected install method
diu upgrade ruff               # upgrade another app via ITS install method
diu status                     # show cache without network
diu audit                      # vulnerability scan
diu snooze ruff==0.4.4 --days 30
diu clear-cache
diu integrity-check
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
