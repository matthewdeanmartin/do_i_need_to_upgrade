# Phase 2 — Checking other apps/packages (the bash use case)

Status: IMPLEMENTED (2026-07-03). Deviations from spec noted inline below.
Prerequisite: Phase 1 (correctness fixes 1–17) is DONE (2026-07-03).

Implementation notes:
- `resolvers.py` holds Target, resolve/resolve_all, the uv/pipx listing
  caches (lru_cache, once per process), and parse_requirements_file.
- `api.check_targets(targets, host=...)` + `api.upgrade_target(target)`;
  exported from the package root along with Target/resolve/resolve_all.
- Watch list lives in the cache under the additive "watch" key
  (Cache.watch_add/watch_remove/watch_list).
- `--quiet` applies to `check` and `audit`.
- Gotcha fixed during implementation: argparse subparsers copy their own
  namespace over the root one, so shared flags use default=SUPPRESS and are
  read via getattr — otherwise `--cache-dir X check` loses its value.
- Not-installed targets appear as VersionInfo(installed="(not installed)")
  plus a note; CLI exits 1 for them (10 wins if other targets have upgrades).

## Problem

The CLI currently defaults to introspecting `do_i_need_to_upgrade` itself.
Nobody uses this tool to check whether *it* needs an upgrade. The real shell
user wants: "is `ruff` / `yt-dlp` / my internal tool out of date?" — from
cron, from a shell prompt hook, from CI.

(The *library* self-check story is separate and is Phase 3; the background
check remains aimed at long-running apps.)

## CLI surface

```bash
diu check ruff                    # one dist, wherever it is installed
diu check ruff black mypy         # several
diu check --requirements reqs.txt # everything pinned in a requirements file
diu watch add yt-dlp              # persist to a watch list in the cache
diu watch remove yt-dlp
diu watch list
diu check --watched               # check the whole watch list
diu upgrade ruff                  # detect THAT dist's install method, upgrade it
```

Design decisions:

1. **Short alias**: add a second console script `diu` (keep the long name too).
   `[project.scripts] diu = "do_i_need_to_upgrade.cli:main"`.
2. **Positional targets**: `check` and `upgrade` take zero or more positional
   dist names. Zero positionals = current behavior (`--dist` default). Keep
   `--dist` for back-compat but document positionals as the way.
3. **Watch list**: stored in the cache JSON under a new `"watch"` key
   (list of names). Bump nothing — additive to schema 1; absent key = empty.

## Resolver chain (finding "other" apps)

`importlib.metadata` only sees the env the CLI runs in. Add
`resolvers.py` with a chain, tried in order, returning
`Target(name, installed_version, install_method) | None`:

1. Current-env metadata (`installed.host_version`) → method via
   `install_method.detect`.
2. `uv tool list` (parse text output; `uv tool list --format json` if/when
   available) → method `UV_TOOL`.
3. `pipx list --json` → method `PIPX`.
4. Fallback: `shutil.which(name)` + `<exe> --version` (best-effort parse;
   method `UNKNOWN`, upgrade unsupported, version may be None).

Not-installed is still useful: `diu check some-tool` with no resolver hit
reports the latest PyPI version and exits with a distinct message + code
(`EXIT_ERROR` with a clear "not installed; latest on PyPI is X" line).

## API changes

Generalize the core:

```python
@dataclass(frozen=True)
class Target:
    name: str
    installed_version: str | None
    install_method: InstallMethod

def check_targets(targets: list[Target], *, cache_dir, allow_network=True,
                  include_prereleases=False) -> Report
```

`check_for_updates` (self/host check) becomes a thin wrapper that builds
targets from the host env (host dist + direct deps) and calls
`check_targets`. Report gains nothing; each target is a `VersionInfo` in
`dependencies` (or a new `targets` tuple — decide when implementing; keep
JSON shape stable if possible, additive only).

`upgrade <name>`: reuse `upgrade_argv(method, name)` — this already works
once the resolver supplies the right method (fixed in Phase 1: pipx/uv-tool
detection now wins over the generic venv check).

## Script-friendly contract (partially DONE in Phase 1)

- Exit codes (DONE): 0 up-to-date / 1 error / 10 upgrades / 11 vulns.
- `--quiet`: print nothing, only set exit code. The crontab idiom:
  `diu check --watched --quiet || notify-send "upgrades available"`.
- `--json` already exists.

## Testing notes

- Mock the resolver subprocess calls (`uv tool list`, `pipx list --json`)
  with recorded fixtures.
- Exit-code matrix test: {up-to-date, upgrade, not-installed, network error}
  × {--quiet, --json, default}.
