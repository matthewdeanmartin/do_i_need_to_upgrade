# Phase 3 — First-class integration for host-app authors (PRIORITY)

Status: SPEC ONLY — not started.
Prerequisite: Phase 2 recommended first (Settings below is shared), but 3
can start with only Phase 1 done.

## Problem

The actual product is other people's apps shipping `my-app upgrade` and a
zero-cost startup check, powered by this library. The primary audience is
**big, long-running apps used daily** — that is what the deferred/background
check (`position="start"` + atexit notification) is designed for. Three
deliverables: an argparse drop-in, programmatic configuration, and
pyproject.toml overrides.

## 3a. Drop-in argparse subcommand — `integrate.py`

```python
# do_i_need_to_upgrade/integrate.py
def add_upgrade_command(
    subparsers: argparse._SubParsersAction,
    dist_name: str,
    *,
    command: str = "upgrade",
    settings: Settings | None = None,
) -> None:
    """Register an 'upgrade' subcommand on the host app's parser."""
    p = subparsers.add_parser(command, help=f"Upgrade {dist_name} to the latest release")
    p.add_argument("--check", action="store_true", help="Only report; do not install")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(_diu_func=functools.partial(_run_upgrade_command, dist_name, settings))

def run_if_upgrade_command(args: argparse.Namespace) -> int | None:
    """Call from the host's main(); returns exit code if it was our command, else None."""
    func = getattr(args, "_diu_func", None)
    return func(args) if func else None
```

Host author writes three lines:

```python
subparsers = parser.add_subparsers(dest="command")
diu.add_upgrade_command(subparsers, dist_name="my-app")
...
if (rc := diu.run_if_upgrade_command(args)) is not None:
    sys.exit(rc)
```

Also provide:

- `add_check_command(subparsers, dist_name, ...)` — same pattern for `check`.
- `install_background_check(dist_name, settings=None)` — the one-liner for
  long-running apps: cached check + background refresh + atexit
  notification. This is THE moment `notify_at_exit=True` is meant for (the
  CLI paths pass False since Phase 1). Internally:
  `check_for_updates(host, position="start", notify_at_exit=True)`.

Conventions: everything stuffed into the Namespace is `_diu_`-prefixed to
avoid collisions; the `set_defaults`-with-callable pattern composes with any
existing dispatch style.

## 3b. Programmatic configuration — `settings.py`

Consolidate the scattered knobs (24h TTL, 14-day cooloff, position,
prereleases, network) into one frozen dataclass:

```python
@dataclass(frozen=True)
class Settings:
    dist_name: str
    cache_dir: Path | None = None          # None -> host.user_cache_dir()
    check_ttl: timedelta = timedelta(hours=24)
    cooloff: timedelta = timedelta(days=14)
    position: Position = "start"
    allow_network: bool = True
    include_prereleases: bool = False
    check_dependencies: bool = True
    audit: bool = False                    # opportunistic audit on check
    notify: Literal["exit-message", "return-only"] = "return-only"
    index_url: str = "https://pypi.org/pypi/{name}/json"   # private index support
    logger: logging.Logger | None = None
```

- Every public API function accepts `settings: Settings`; keep accepting
  `Host` for back-compat (build a Settings from it internally).
- `Cache.is_fresh(ttl=...)` and cooloff must read from Settings, not module
  constants (`DEFAULT_TTL`/`COOLOFF` become defaults only).
- `index_url` requires relaxing `validate_pypi_url` to validate against the
  configured host instead of hard-coded pypi.org (keep https-only).

## 3c. pyproject.toml override — two sides

**App-author side** (shipped defaults):

```toml
[tool.do_i_need_to_upgrade]
enabled = true
position = "start"
cooloff_days = 7
check_dependencies = false
notify = "exit-message"
```

Loader `Settings.from_pyproject(path=None, dist_name=...)`:
- Dev scenario: walk up from cwd for `pyproject.toml`.
- Deployed scenario: pyproject.toml is NOT installed with wheels — support a
  package data file (`my_app/do_i_need_to_upgrade.toml`) looked up via
  `importlib.resources`, or read `[tool.*]` at build time is out of scope.
- `tomllib` is stdlib on 3.11+; project floor is 3.10 → use
  `tomllib` when available, degrade to no-op (defaults) on 3.10, or vendor a
  minimal TOML reader. Decision: degrade on 3.10, document it.

**End-user side** (opt-out — ethically mandatory for phone-home behavior):

Precedence: **env var > user config > app settings > defaults**.

- `DO_I_NEED_TO_UPGRADE=off` — disable entirely (position forced to "off").
- `DO_I_NEED_TO_UPGRADE=no-network` — cache-only.
- User config `~/.config/do_i_need_to_upgrade.toml` (XDG / platform
  equivalent) for per-package disable/snooze.
- Document the kill switch prominently in README.

`Settings.resolve()` applies the precedence chain; the integrate.py entry
points and `check_for_updates` call it once at the boundary.

## Module layout

```
do_i_need_to_upgrade/
  integrate.py   # add_upgrade_command, run_if_upgrade_command, install_background_check
  settings.py    # Settings, from_pyproject, from_env, resolve
  api.py         # existing functions, now Settings-driven
```

## Testing notes

- integrate: build a toy argparse app in the test, assert dispatch and
  non-collision with host args.
- settings precedence: env var beats pyproject beats defaults.
- 3.10 vs 3.11 tomllib path (skipif).
