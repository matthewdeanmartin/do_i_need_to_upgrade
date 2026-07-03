"""Generate dist/diu_lite.py — the single-file, stdlib-only update checker.

The lite build is a generated artifact, not a second codebase: shared code is
extracted verbatim from source regions marked with ``# lite: begin <name>`` /
``# lite: end <name>`` comments (cache.py, pypi.py), and only the lite-specific
glue (naive version comparison, tiny JSON cache, the public
``check_for_updates``) lives in the template below.

Usage:
    uv run python scripts/build_lite.py [output-path]

tests/test_lite.py regenerates the file on every run and exercises it, so the
lite build cannot silently drift from the package.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "do_i_need_to_upgrade"
DEFAULT_OUTPUT = ROOT / "dist" / "diu_lite.py"

_MARKER = re.compile(r"^# lite: begin (?P<name>[\w-]+)\n(?P<body>.*?)^# lite: end (?P=name)\n", re.M | re.S)


def _read_version() -> str:
    """Read __version__ from __about__.py without importing the package.

    Returns:
        The version string, or '0.0.0' if it cannot be found.
    """
    text = (PACKAGE / "__about__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0.0.0"


def _extract_regions(path: Path) -> dict[str, str]:
    """Extract all marked lite regions from a source file.

    Args:
        path: Source file to scan.

    Returns:
        Mapping of region name to its verbatim source text.
    """
    text = path.read_text(encoding="utf-8")
    return {m.group("name"): m.group("body").strip("\n") for m in _MARKER.finditer(text)}


HEADER_TEMPLATE = '''"""do_i_need_to_upgrade LITE — single-file, stdlib-only update checker.

Copy this file into your project (keep this header). It answers exactly one
question at startup: "is a newer release of my app on PyPI?"

    from yourapp import diu_lite
    message = diu_lite.check_for_updates("your-dist-name")
    if message:
        print(message, file=sys.stderr)

- Zero dependencies (stdlib only), one file, MIT licensed.
- Caches to a small JSON sidecar; refreshes on a background daemon thread
  (pass sync=True to refresh in the foreground instead).
- Naive numeric version comparison: pre/dev/post releases are ignored as
  upgrade candidates. Install the full ``do_i_need_to_upgrade`` package for
  PEP 440 comparison, dependency checks, audits, and self-upgrade.
- End users can set DO_I_NEED_TO_UPGRADE=off (disable) or =no-network.

Generated from do_i_need_to_upgrade {version} on {date} by
scripts/build_lite.py — DO NOT EDIT; regenerate instead.
License: MIT (https://github.com/matthewdeanmartin/do_i_need_to_upgrade)
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path

__version__ = "{version}"
'''

LITE_TEMPLATE = '''

# ── lite-specific code (naive version compare + tiny cache + public API) ─────

CACHE_FILENAME = "diu_lite.json"
_NUMERIC_RELEASE = re.compile(r"^\\d+(\\.\\d+)*$")
ENV_VAR = "DO_I_NEED_TO_UPGRADE"


def _version_tuple(version: str) -> tuple[int, ...]:
    """Naive numeric version tuple: '1.2.3' -> (1, 2, 3), trailing zeros dropped."""
    parts: list[int] = []
    for chunk in version.split("."):
        match = re.match(r"(\\d+)", chunk)
        if not match:
            break
        parts.append(int(match.group(1)))
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _is_newer(latest: str, installed: str) -> bool:
    """True if latest is strictly newer than installed (numeric compare)."""
    return _version_tuple(latest) > _version_tuple(installed)


def _latest_from_payload(payload: dict) -> str | None:
    """Newest plain-numeric, non-yanked release key from a PyPI JSON payload."""
    releases = payload.get("releases")
    candidates: list[str] = []
    if isinstance(releases, dict):
        for key, files in releases.items():
            if isinstance(key, str) and _NUMERIC_RELEASE.match(key) and not _is_yanked_release(files):
                candidates.append(key)
    if candidates:
        return max(candidates, key=_version_tuple)
    info_version = (payload.get("info") or {}).get("version")
    if isinstance(info_version, str) and _NUMERIC_RELEASE.match(info_version):
        return info_version
    return None


def _default_cache_dir(dist_name: str) -> Path:
    """Per-user cache directory (never the world-shared tempdir)."""
    leaf = f"diu_lite-{dist_name}"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / leaf / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / leaf
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / leaf


def _load_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(path: Path, data: dict) -> None:
    """Atomic write (tempfile + os.replace); failures are silently ignored."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".diu.", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp_name, path)
    except OSError:
        pass


def check_for_updates(
    dist_name: str,
    cache_dir: str | Path | None = None,
    ttl_hours: float = 24.0,
    sync: bool = False,
    timeout: float = TIMEOUT_SECONDS,
) -> str | None:
    """Return an 'update available' message for dist_name, or None.

    Reads the cache in the foreground; when the entry is stale, refreshes
    from PyPI on a daemon thread (the message then appears on the *next*
    start — intended for long-running apps) or synchronously with sync=True.

    Honors the DO_I_NEED_TO_UPGRADE env var: 'off' disables entirely,
    'no-network' reads the cache but never fetches.
    """
    env = os.environ.get(ENV_VAR, "").strip().lower()
    if env in {"off", "0", "false", "disabled"}:
        return None
    allow_network = env not in {"no-network", "no_network", "cache-only"}

    try:
        installed_version = metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None

    directory = Path(cache_dir) if cache_dir else _default_cache_dir(dist_name)
    path = directory / CACHE_FILENAME
    data = _load_cache(path)
    entry = data.get(dist_name)
    entry = entry if isinstance(entry, dict) else {}

    fetched = parse_iso(entry.get("fetched"))
    fresh = bool(fetched and (utcnow() - fetched) < timedelta(hours=ttl_hours))
    if not fresh and allow_network:

        def refresh() -> None:
            try:
                payload = fetch_package_json(dist_name, timeout=timeout)
            except PypiError:
                return
            latest_seen = _latest_from_payload(payload)
            if latest_seen:
                current = _load_cache(path)
                current[dist_name] = {"latest": latest_seen, "fetched": format_iso(utcnow())}
                _save_cache(path, current)

        if sync:
            refresh()
            data = _load_cache(path)
            entry = data.get(dist_name)
            entry = entry if isinstance(entry, dict) else {}
        else:
            threading.Thread(target=refresh, name="diu-lite-refresh", daemon=True).start()

    latest = entry.get("latest")
    if isinstance(latest, str) and _is_newer(latest, installed_version):
        return f"[update] {dist_name} {installed_version} -> {latest} is available"
    return None


__all__ = ["PypiError", "check_for_updates", "__version__"]
'''


def build(output: Path = DEFAULT_OUTPUT) -> Path:
    """Generate the single-file lite module.

    Args:
        output: Where to write the generated file.

    Returns:
        The output path.

    Raises:
        SystemExit: If an expected lite region is missing from the sources.
    """
    regions: dict[str, str] = {}
    regions.update(_extract_regions(PACKAGE / "cache.py"))
    regions.update(_extract_regions(PACKAGE / "pypi.py"))

    expected = ("pypi-constants", "pypi-error", "pypi-fetch", "time-helpers")
    missing = [name for name in expected if name not in regions]
    if missing:
        raise SystemExit(f"missing lite regions in sources: {missing}")

    version = _read_version()
    parts = [
        HEADER_TEMPLATE.format(version=version, date=date.today().isoformat()),
        "\n# ── shared code, extracted verbatim from the do_i_need_to_upgrade package ──\n",
        regions["pypi-constants"],
        "\n\n",
        regions["pypi-error"],
        "\n\n",
        regions["time-helpers"],
        "\n\n",
        regions["pypi-fetch"],
        "\n",
        LITE_TEMPLATE,
    ]
    source = "".join(parts)
    compile(source, str(output), "exec")  # fail the build on any syntax error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source, encoding="utf-8")
    return output


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    written = build(target)
    line_count = len(written.read_text(encoding="utf-8").splitlines())
    print(f"wrote {written} ({line_count} lines)")
