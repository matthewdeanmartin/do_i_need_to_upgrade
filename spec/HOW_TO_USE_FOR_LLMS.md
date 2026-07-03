# HOW_TO_USE_FOR_LLMS

Use this when an LLM is asked to wire `do_i_need_to_upgrade` into an existing Python app.

## Goal

Do not stop after adding the dependency.

Real integration means the host app:

- checks for updates during normal app execution
- surfaces a user-visible notice without requiring a separate `do_i_need_to_upgrade` CLI invocation
- exposes host-app subcommands such as `my_app upgrade` and `my_app check-updates`

## Minimum integration checklist

1. Add `do_i_need_to_upgrade` as a runtime dependency in the host app's `[project.dependencies]`.
2. Do not use a local editable path override unless the user explicitly asks for local dogfooding.
3. Add integrated argparse subcommands with:
   - `add_upgrade_command(...)`
   - `add_check_command(...)`
   - `run_if_upgrade_command(args)`
4. Hook update checking into the host app's real lifecycle:
   - startup for cached check + background refresh
   - exit for a cache-only reread so the refreshed result can be shown
5. Add tests for:
   - subcommand parsing
   - dispatcher behavior
   - startup/exit notice behavior
6. Run the host app's normal `uv`-based test flow.

## Dependency rule

At the time of writing, PyPI has `do-i-need-to-upgrade 0.0.1` published.

Use:

```toml
dependencies = [
    "do_i_need_to_upgrade>=0.0.1",
]
```

Do not invent a higher floor unless that version is actually published.

## Recommended host pattern

Create a small host-local helper module such as `my_app/upgrade_integration.py`.

Suggested responsibilities:

- define `DIST_NAME`
- define `Settings(dist_name=..., position="start", notify="return-only")`
- register `upgrade` and `check-updates` subcommands
- provide `startup_report()`
- provide `exit_report()`
- provide `render_notice(report)`

Example shape:

```python
from do_i_need_to_upgrade import add_check_command, add_upgrade_command, run_if_upgrade_command
from do_i_need_to_upgrade.api import check_for_updates
from do_i_need_to_upgrade.settings import Settings

DIST_NAME = "my_app"


def settings() -> Settings:
    return Settings(dist_name=DIST_NAME, position="start", notify="return-only")


def add_commands(subparsers) -> None:
    active_settings = settings()
    add_upgrade_command(subparsers, DIST_NAME, command="upgrade", settings=active_settings)
    add_check_command(subparsers, DIST_NAME, command="check-updates", settings=active_settings)


def run_command(args):
    return run_if_upgrade_command(args)


def startup_report():
    report = check_for_updates(settings=settings())
    return report if not report.is_empty else None


def exit_report():
    report = check_for_updates(settings=settings().replace(allow_network=False, notify="return-only"))
    return report if not report.is_empty else None
```

## CLI integration

### If the app already uses subparsers

This is the easy case.

Add the updater commands to the existing `subparsers`, then dispatch immediately after parsing:

```python
args = parser.parse_args(argv)

if (result := run_command(args)) is not None:
    return result
```

Then continue with the app's own commands.

This is how `ftplib_gui` was wired.

### If the app does not use subparsers

Be careful not to break existing positional arguments.

If the app treats the first positional argument as something else, like a URL, detect whether the argv is really asking for `upgrade` or `check-updates` before handing off to a dedicated parser.

This is how `urllib_gui` was wired.

## GUI / long-running app integration

For desktop or long-running apps, do not make the user run a separate updater command.

Recommended flow:

1. On startup, call `startup_report()`.
2. If it returns a non-empty report, render it to stderr immediately.
3. Let the app continue running so the background refresh can land in the cache.
4. When the app exits, call `exit_report()`.
5. Render the exit report if it is non-empty and different from the startup message.

That gives:

- fast startup
- no extra blocking network call at shutdown
- a fresh notice after a long-running session

## `install_background_check(...)` vs explicit lifecycle control

`install_background_check(dist_name)` is valid for simple apps.

For apps that want tighter control over where and when terminal notices appear, use explicit `check_for_updates(...)` calls with host-managed rendering, as done in `urllib_gui` and `ftplib_gui`.

Use explicit lifecycle control when:

- the host app already owns startup/shutdown flow
- you want to suppress duplicate notices
- you want startup and exit behavior in a GUI app

## Files an LLM should usually touch

- `pyproject.toml`
- package metadata file such as `__about__.py`
- CLI entrypoint such as `cli.py`
- module runner such as `__main__.py`
- GUI/app lifecycle file such as `app.py`
- new helper module such as `upgrade_integration.py`
- CLI/app tests
- changelog
- `uv.lock` after sync

## What "done" looks like

The work is done when all of the following are true:

- `my_app upgrade` works
- `my_app check-updates` works
- normal app launch still works
- the app prints update notices during normal usage without needing the standalone updater CLI
- tests pass
- no local editable path override remains unless explicitly requested

## Real examples

- `C:\github\urllib_gui`
- `C:\github\ftplib_gui`

Those two repos are the reference integrations for future LLM work.
