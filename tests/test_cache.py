"""Tests for the Cache module."""

from __future__ import annotations

import tempfile
from pathlib import Path

from do_i_need_to_upgrade.cache import Cache, format_iso, parse_iso, utcnow


def test_empty_cache_load() -> None:
    """Empty cache loads without error."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        assert cache.data["schema"] == 1


def test_put_and_get_package() -> None:
    """put_package / get_package round-trips."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        now = utcnow()
        cache.put_package("my-pkg", "1.2.3", now)
        entry = cache.get_package("my-pkg")
        assert entry is not None
        assert entry["latest"] == "1.2.3"


def test_is_fresh() -> None:
    """Cache entry is fresh right after writing."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.put_package("pkg", "1.0", utcnow())
        assert cache.is_fresh("pkg")


def test_is_not_fresh_missing() -> None:
    """Missing entry is not fresh."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        assert not cache.is_fresh("pkg")


def test_snooze_and_is_snoozed() -> None:
    """Snooze / is_snoozed lifecycle."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.snooze("pkg==1.0", 30)
        assert cache.is_snoozed("pkg==1.0")


def test_snooze_negative_days_not_snoozed() -> None:
    """Negative snooze is immediately expired."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.snooze("pkg==1.0", -1)
        assert not cache.is_snoozed("pkg==1.0")


def test_prune_snoozes() -> None:
    """Expired snoozes are pruned."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.snooze("pkg==1.0", -1)  # already expired
        cache.prune_snoozes()
        assert not cache.is_snoozed("pkg==1.0")


def test_save_and_reload() -> None:
    """Cache persists across save/load cycles."""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        cache = Cache.load(p)
        cache.put_package("mypkg", "2.0", utcnow())
        cache.save()
        reloaded = Cache.load(p)
        assert reloaded.get_package("mypkg") is not None


def test_clear() -> None:
    """clear() empties the cache."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.put_package("pkg", "1.0", utcnow())
        cache.clear()
        assert cache.get_package("pkg") is None


def test_parse_iso_none() -> None:
    """parse_iso returns None for None input."""
    assert parse_iso(None) is None


def test_parse_iso_valid() -> None:
    """parse_iso parses a valid ISO string."""
    dt = parse_iso("2025-01-01T00:00:00Z")
    assert dt is not None
    assert dt.year == 2025


def test_format_iso_roundtrip() -> None:
    """format_iso / parse_iso round-trips."""
    now = utcnow()
    formatted = format_iso(now)
    parsed = parse_iso(formatted)
    assert parsed is not None
    assert abs((now - parsed).total_seconds()) < 1


def test_watch_add_and_list() -> None:
    """watch_add persists names, sorted and deduplicated."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        assert cache.watch_list() == []
        assert cache.watch_add("zeta")
        assert cache.watch_add("alpha")
        assert not cache.watch_add("alpha")
        assert cache.watch_list() == ["alpha", "zeta"]


def test_watch_remove() -> None:
    """watch_remove drops present names and reports absence."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.watch_add("pkg")
        assert cache.watch_remove("pkg")
        assert not cache.watch_remove("pkg")
        assert cache.watch_list() == []


def test_watch_survives_save_load() -> None:
    """Watch list round-trips through save/load."""
    with tempfile.TemporaryDirectory() as d:
        cache = Cache.load(Path(d))
        cache.watch_add("pkg")
        cache.save()
        reloaded = Cache.load(Path(d))
        assert reloaded.watch_list() == ["pkg"]
