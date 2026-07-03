"""Anti-drift tests for the generated single-file lite build.

Regenerates dist/diu_lite.py from the current sources on every run and
exercises it, so the lite build can never silently drift from the package.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from datetime import timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def lite(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """Build diu_lite.py from the current sources and import it."""
    spec = importlib.util.spec_from_file_location("build_lite", ROOT / "scripts" / "build_lite.py")
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    output = tmp_path_factory.mktemp("lite") / "diu_lite.py"
    builder.build(output)

    mod_spec = importlib.util.spec_from_file_location("diu_lite", output)
    assert mod_spec is not None and mod_spec.loader is not None
    module = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(module)
    return module


def test_lite_is_stdlib_only(lite: ModuleType) -> None:
    """Every import in the generated file is a stdlib module."""
    source = Path(lite.__file__ or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    non_stdlib = imported - set(sys.stdlib_module_names) - {"__future__"}
    assert not non_stdlib, f"lite build imports non-stdlib modules: {non_stdlib}"


def test_lite_version_tuple(lite: ModuleType) -> None:
    """Naive tuple compare handles trailing zeros."""
    assert lite._version_tuple("1.2.3") == (1, 2, 3)
    assert lite._version_tuple("1.0") == lite._version_tuple("1.0.0")


def test_lite_is_newer(lite: ModuleType) -> None:
    """Strictly-newer comparison, including the equal-after-padding case."""
    assert lite._is_newer("1.2.0", "1.1.9")
    assert not lite._is_newer("1.0", "1.0.0")
    assert not lite._is_newer("0.9.0", "1.0.0")


def test_lite_latest_from_payload_skips_yanked_and_prereleases(lite: ModuleType) -> None:
    """Only plain numeric, non-yanked releases are candidates."""
    payload = {
        "info": {"version": "3.0.0rc1"},
        "releases": {
            "1.0.0": [{"yanked": False}],
            "2.0.0": [{"yanked": True}],
            "3.0.0rc1": [{"yanked": False}],
        },
    }
    assert lite._latest_from_payload(payload) == "1.0.0"


def _seed(cache_dir: Path, dist: str, latest: str, lite: ModuleType) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {dist: {"latest": latest, "fetched": lite.format_iso(lite.utcnow())}}
    (cache_dir / "diu_lite.json").write_text(json.dumps(payload), encoding="utf-8")


def test_lite_check_reports_upgrade(lite: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cached newer version yields the update message, cache-only."""
    monkeypatch.setenv("DO_I_NEED_TO_UPGRADE", "no-network")
    _seed(tmp_path, "packaging", "999.0", lite)
    message = lite.check_for_updates("packaging", cache_dir=tmp_path)
    assert message is not None
    assert "packaging" in message and "999.0" in message


def test_lite_check_up_to_date(lite: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No message when the cached latest is not newer."""
    monkeypatch.setenv("DO_I_NEED_TO_UPGRADE", "no-network")
    _seed(tmp_path, "packaging", "0.0.1", lite)
    assert lite.check_for_updates("packaging", cache_dir=tmp_path) is None


def test_lite_check_not_installed(lite: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An uninstalled dist yields None instead of raising."""
    monkeypatch.setenv("DO_I_NEED_TO_UPGRADE", "no-network")
    assert lite.check_for_updates("definitely-not-installed-xyz", cache_dir=tmp_path) is None


def test_lite_kill_switch(lite: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DO_I_NEED_TO_UPGRADE=off disables everything."""
    monkeypatch.setenv("DO_I_NEED_TO_UPGRADE", "off")
    _seed(tmp_path, "packaging", "999.0", lite)
    assert lite.check_for_updates("packaging", cache_dir=tmp_path) is None


def test_lite_shared_helpers_roundtrip(lite: ModuleType) -> None:
    """The extracted time helpers behave like the package originals."""
    now = lite.utcnow()
    assert now.tzinfo == timezone.utc
    parsed = lite.parse_iso(lite.format_iso(now))
    assert parsed is not None
    assert abs(now - parsed) < timedelta(seconds=1)


def test_lite_validate_name_guard(lite: ModuleType) -> None:
    """The extracted name validator still rejects bad names."""
    with pytest.raises(lite.PypiError):
        lite.validate_name("-bad-name")
