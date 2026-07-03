# Phase 4 — Vendoring instructions + single-file "lite" build

Status: SPEC ONLY — not started. Do this LAST (wants a stable codebase).

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
