# Minimal-dependency integration

If you want `do_i_need_to_upgrade` without making it part of your app's base
runtime dependencies, these are the two recommended paths:

## Option 1 — host-app optional extras

Keep the integration in your app, but make the dependency optional:

```toml
[project]
dependencies = []

[project.optional-dependencies]
all = [
  "do_i_need_to_upgrade>=0.0.1",
]
```

Then structure your host app so it quietly skips update integration when the
extra is not installed:

```python
try:
    from do_i_need_to_upgrade import add_upgrade_command
except ImportError:
    add_upgrade_command = None


if add_upgrade_command is not None:
    add_upgrade_command(subparsers, dist_name="your-app")
```

This pattern is good when:

- you want full `do_i_need_to_upgrade` behavior
- you do not want the base install to pull extra dependencies
- you are willing to make update checks a feature of `your-app[all]`

## Option 2 — the single-file lite build (`diu_lite.py`)

A generated, stdlib-only, ~350-line single file that answers exactly one
question at startup: *"is a newer release of my app on PyPI?"*

```python
from yourapp import diu_lite

message = diu_lite.check_for_updates("your-dist-name")
if message:
    print(message, file=sys.stderr)
```

- **Zero dependencies** — no `packaging`; version comparison is naive numeric
  tuples, so pre/dev/post releases are simply ignored as upgrade candidates.
- Caches to a per-user JSON sidecar; when stale it refreshes on a background
  daemon thread, so the message appears on the *next* start (long-running-app
  friendly). Pass `sync=True` to refresh in the foreground instead.
- Honors the end-user kill switch: `DO_I_NEED_TO_UPGRADE=off` or
  `=no-network`.
- Not in lite: dependency checks, audits, self-upgrade, snoozes, cooloff,
  private indexes. Those are what the full package is for.

### Getting the file

Build it from a source checkout:

```bash
make build-lite          # writes dist/diu_lite.py
```

Then copy `dist/diu_lite.py` into your project, keeping its header (it embeds
the source version, generation date, and MIT license notice).

### How it stays honest

`diu_lite.py` is a **generated artifact, not a second codebase**. The shared
parts (PyPI fetch with name/URL validation, ISO time helpers) are extracted
verbatim from the package sources via `# lite: begin/end` markers by
`scripts/build_lite.py`; only the naive version compare, the tiny cache, and
the public `check_for_updates` are lite-specific. `tests/test_lite.py`
regenerates and exercises the file on every test run, so it cannot drift.

## Which one should you choose?

Choose **optional extras** when you want:

- integrated `upgrade` and `check-updates` commands
- installer-aware self-upgrade behavior
- dependency checks, snoozes, cooloff, and settings support

Choose **`diu_lite.py`** when you want:

- the fewest possible dependencies
- a single vendored file
- only the simple "is there a newer release on PyPI?" startup check
