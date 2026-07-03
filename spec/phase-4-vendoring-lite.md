# Phase 4 — Vendoring instructions + single-file "lite" build

Status: IMPLEMENTED (2026-07-03). Deviations noted here.

Implementation notes:
- All package-internal imports converted to relative (`from . import x`) —
  the package is copy-paste vendorable. Docs: docs/usage/vendoring.md.
- `scripts/build_lite.py` generates `dist/diu_lite.py` (~350 lines) from
  `# lite: begin/end <name>` regions in cache.py (time-helpers) and pypi.py
  (pypi-constants, pypi-error, pypi-fetch), plus a lite-only template
  (naive version tuple compare with trailing-zero normalization, tiny JSON
  cache, `check_for_updates(dist, cache_dir=None, ttl_hours=24, sync=False)`).
- Lite skips non-numeric release keys entirely, so pre/dev/post releases are
  never upgrade candidates (documented in the generated header).
- Lite honors DO_I_NEED_TO_UPGRADE=off / no-network (same kill switch).
- The generated file is NOT committed; `make build-lite` produces it, and
  `tests/test_lite.py` regenerates + exercises it every test run (including
  an AST check that all imports are stdlib) — that is the anti-drift gate.
- `make prerelease` now includes build-lite.

## Tier 1: vendoring the full package (docs + one code change)

The package is nearly stdlib-only; the only runtime dep is `packaging`.

Required code change to make vendoring copy-paste clean: **switch internal
imports from absolute (`from do_i_need_to_upgrade import cache`) to relative
(`from . import cache`)** — this is why pip's own `_vendor` policy demands
relative imports. After that, docs are just:

```
1. Copy do_i_need_to_upgrade/ into yourapp/_vendor/diu/
2. Import as `from yourapp._vendor import diu`
3. You still need `packaging` (you almost certainly already have it), or use Tier 2.
```

Add `docs/vendoring.md` with the above plus license note (MIT, keep the
LICENSE file alongside the vendored copy).

## Tier 2 (recommended): generated single-file `diu_lite.py`

~250 lines, stdlib-only, no `packaging`. Scope: the ONE thing embedders need
at startup of a long-running app:

- `check_for_updates(dist_name, cache_dir=None) -> str | None`
  — returns the "update available" message or None. Nothing else.
- Stdlib-only version compare — a small `version_tuple`/`satisfies`-style
  comparer (like the hand-rolled one that lived in integrity_check.py before
  Phase 1 replaced it with `packaging`; recover it from git history:
  commit before 2026-07-03, functions `version_tuple` + `satisfies`).
  Good enough for "is latest > installed"; document the imprecision.
- JSON cache with TTL + atomic write (trimmed cache.py).
- urllib PyPI fetch (trimmed pypi.py; keep name/URL validation and timeout).
- Explicitly NOT in lite: audit, self-upgrade, dependency walking,
  snooze/cooloff config, install-method detection.

### Build as a generated artifact, not a second codebase

- Mark source regions with `# lite: begin` / `# lite: end` comments in
  cache.py, pypi.py, api.py.
- `scripts/build_lite.py` concatenates the regions into `dist/diu_lite.py`
  with a header: source version, generation date, license, "do not edit".
- CI check: a test imports the generated file and runs a shared core test
  set against it (parametrize the same tests over `do_i_need_to_upgrade`
  and `diu_lite` where the surface overlaps), so lite can never drift.

### Docs story

README gets a section: "either `pip install do_i_need_to_upgrade`, or copy
`diu_lite.py` into your project — MIT, self-contained, zero deps."
