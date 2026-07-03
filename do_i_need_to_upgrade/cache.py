"""JSON-sidecar cache with TTL, cooloff, and per-target snoozes.

The cache is stored as a single JSON file in the host's cache_dir.
All writes use an atomic tempfile rename to prevent corruption.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = 1
FILENAME = "do_i_need_to_upgrade.json"
DEFAULT_TTL = timedelta(hours=24)
COOLOFF = timedelta(days=14)


# lite: begin time-helpers
def utcnow() -> datetime:
    """Return the current UTC datetime.

    Returns:
        Current UTC datetime with timezone info.
    """
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string.

    Args:
        value: ISO 8601 string or None.

    Returns:
        Datetime with timezone info, or None if value is empty/invalid.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    """Format a datetime as an ISO 8601 UTC string.

    Args:
        dt: Datetime to format.

    Returns:
        ISO 8601 string with Z suffix.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# lite: end time-helpers


@dataclass
class Cache:
    """JSON sidecar cache for PyPI metadata and snooze records."""

    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, cache_dir: Path) -> Cache:
        """Load or create the sidecar cache file.

        Args:
            cache_dir: Directory containing the cache file.

        Returns:
            A Cache instance with the loaded or default data.
        """
        path = cache_dir / FILENAME
        data: dict[str, Any] = {"schema": SCHEMA, "pypi": {}, "suppressed_until": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("schema") == SCHEMA:
                    data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        return cls(path=path, data=data)

    def save(self) -> None:
        """Atomically write the cache to disk.

        Uses a tempfile + rename for crash safety. Sets file permissions to 0o600.

        There is deliberately no cross-process locking: concurrent writers do a
        whole-file load-modify-replace, so the last writer wins and may drop the
        other's changes. os.replace only guarantees the file is never corrupt.
        Acceptable for an advisory cache; do not store must-not-lose data here.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".dinu.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        with contextlib.suppress(OSError, NotImplementedError):
            os.chmod(self.path, 0o600)

    def get_package(self, name: str) -> dict[str, Any] | None:
        """Return cached metadata for a package, or None.

        Args:
            name: Package name.

        Returns:
            Dict with keys latest, published, fetched; or None if not cached.
        """
        packages = self.data.get("pypi")
        if not isinstance(packages, dict):
            return None
        entry = packages.get(name)
        return entry if isinstance(entry, dict) else None

    def put_package(self, name: str, latest: str, published: datetime | None) -> None:
        """Store package metadata in the cache.

        Args:
            name: Package name.
            latest: Latest version string.
            published: Publish datetime of the latest version, or None.
        """
        self.data.setdefault("pypi", {})[name] = {
            "latest": latest,
            "published": format_iso(published) if published else None,
            "fetched": format_iso(utcnow()),
        }

    def is_fresh(self, name: str, ttl: timedelta = DEFAULT_TTL) -> bool:
        """Return True if the cache entry is still within its TTL.

        Args:
            name: Package name.
            ttl: Maximum acceptable age. Defaults to 24 hours.

        Returns:
            True if the cached entry exists and is younger than ttl.
        """
        entry = self.get_package(name)
        if not entry:
            return False
        fetched = parse_iso(entry.get("fetched"))
        if not fetched:
            return False
        return utcnow() - fetched < ttl

    def published_age(self, name: str) -> timedelta | None:
        """Return the age of the latest release, or None if unknown.

        Args:
            name: Package name.

        Returns:
            Timedelta since the latest release was published, or None.
        """
        entry = self.get_package(name)
        if not entry:
            return None
        published = parse_iso(entry.get("published"))
        if not published:
            return None
        return utcnow() - published

    def is_in_cooloff(self, name: str) -> bool:
        """Return True if the latest release is within the 14-day cooloff window.

        Args:
            name: Package name.

        Returns:
            True if the release is younger than COOLOFF.
        """
        age = self.published_age(name)
        if age is None:
            return False
        return age < COOLOFF

    def snooze(self, target: str, days: int) -> None:
        """Snooze upgrade suggestions for a specific target for a number of days.

        Args:
            target: Target identifier, e.g. 'my-app==1.2.3'.
            days: Number of days to snooze.
        """
        until = utcnow() + timedelta(days=days)
        self.data.setdefault("suppressed_until", {})[target] = format_iso(until)

    def is_snoozed(self, target: str) -> bool:
        """Return True if the given target is currently snoozed.

        Args:
            target: Target identifier.

        Returns:
            True if currently within the snooze window.
        """
        until_str = self.data.get("suppressed_until", {}).get(target)
        until = parse_iso(until_str)
        if not until:
            return False
        return utcnow() < until

    def prune_snoozes(self) -> None:
        """Remove expired snooze entries from the cache."""
        now = utcnow()
        snoozes = self.data.get("suppressed_until", {})
        for key in list(snoozes.keys()):
            until = parse_iso(snoozes.get(key))
            if not until or until <= now:
                del snoozes[key]

    def watch_list(self) -> list[str]:
        """Return the persisted watch list of package names.

        Returns:
            Sorted list of watched package names (empty if none).
        """
        watch = self.data.get("watch")
        if not isinstance(watch, list):
            return []
        return [str(name) for name in watch]

    def watch_add(self, name: str) -> bool:
        """Add a package name to the watch list.

        Args:
            name: Package name to watch.

        Returns:
            True if added, False if it was already present.
        """
        names = self.watch_list()
        if name in names:
            return False
        names.append(name)
        self.data["watch"] = sorted(names)
        return True

    def watch_remove(self, name: str) -> bool:
        """Remove a package name from the watch list.

        Args:
            name: Package name to stop watching.

        Returns:
            True if removed, False if it was not present.
        """
        names = self.watch_list()
        if name not in names:
            return False
        names.remove(name)
        self.data["watch"] = names
        return True

    def set_audit(self, tool: str, summary: dict[str, Any]) -> None:
        """Record the last audit result.

        Args:
            tool: Name of the audit tool used.
            summary: Dict of audit summary data.
        """
        self.data["last_audit_utc"] = format_iso(utcnow())
        self.data["audit_summary"] = {"tool": tool, **summary}

    def audit_is_fresh(self, ttl: timedelta = DEFAULT_TTL) -> bool:
        """Return True if the last audit result is still within TTL.

        Args:
            ttl: Maximum acceptable age. Defaults to 24 hours.

        Returns:
            True if the audit result is younger than ttl.
        """
        fetched = parse_iso(self.data.get("last_audit_utc"))
        if not fetched:
            return False
        return utcnow() - fetched < ttl

    def clear(self) -> None:
        """Reset the cache to its empty initial state."""
        self.data = {"schema": SCHEMA, "pypi": {}, "suppressed_until": {}}


__all__ = ["COOLOFF", "DEFAULT_TTL", "Cache", "format_iso", "parse_iso", "utcnow"]
