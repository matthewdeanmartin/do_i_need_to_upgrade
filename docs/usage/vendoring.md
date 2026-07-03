# Vendoring and the single-file lite build

You do not have to add `do_i_need_to_upgrade` as a dependency. Two supported
alternatives, in increasing order of minimalism:

## Option 1 — vendor the full package

The package uses relative imports internally, so it is copy-paste vendorable:

1. Copy the `do_i_need_to_upgrade/` directory into your project, e.g.
   `yourapp/_vendor/diu/` (any directory name works — imports are relative).
1. Keep the `LICENSE` file (MIT) alongside the vendored copy.
1. Import it from its new home:
   ```python
   from yourapp._vendor import diu
   diu.install_background_check("your-app")
   ```
1. You still need `packaging` at runtime — you almost certainly already have
   it (pip, setuptools, and most tools depend on it). If you want zero
   dependencies, use option 2.

To update, re-copy the directory from a newer release. Note the version you
vendored in a comment or a `VENDORED.txt` so upgrades are traceable.

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
