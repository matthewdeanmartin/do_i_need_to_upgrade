"""Stdlib-only PyPI JSON client.

Provides package metadata fetching with URL and name validation,
prerelease handling, yanked version detection, and dev release detection.
All network I/O uses the stdlib only (urllib.request + ssl).
The ``packaging`` library is used for robust version comparison.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import NamedTuple

from packaging.version import InvalidVersion, Version
from packaging.version import parse as parse_version

# lite: begin pypi-constants
PYPI_HOST = "pypi.org"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
USER_AGENT = "do-i-need-to-upgrade/1 (+https://github.com/matthewdeanmartin/do_i_need_to_upgrade)"
TIMEOUT_SECONDS = 5.0
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
# lite: end pypi-constants


# lite: begin pypi-error
class PypiError(RuntimeError):
    """PyPI fetch or parse failure."""


# lite: end pypi-error


class VersionDetail(NamedTuple):
    """Parsed version detail from PyPI."""

    latest: str
    published: datetime | None
    latest_stable: str | None
    is_prerelease: bool
    is_yanked: bool
    is_dev: bool


# lite: begin pypi-fetch
def validate_name(name: str) -> str:
    """Validate a PyPI package name.

    Args:
        name: The package name to validate.

    Returns:
        The validated name.

    Raises:
        PypiError: If name does not match the allowed pattern.
    """
    if not NAME_PATTERN.match(name):
        raise PypiError(f"invalid package name: {name!r}")
    return name


def validate_pypi_url(url: str) -> str:
    """Validate that a URL points to pypi.org over HTTPS.

    Args:
        url: URL to validate.

    Returns:
        The validated URL.

    Raises:
        PypiError: If the URL does not point to pypi.org over HTTPS.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != PYPI_HOST:
        raise PypiError(f"refusing to fetch non-PyPI URL: {url!r}")
    return url


def validate_https_url(url: str) -> str:
    """Validate that a URL uses HTTPS and has a hostname.

    Used for custom index URLs; the default pypi.org template additionally
    pins the hostname via validate_pypi_url.

    Args:
        url: URL to validate.

    Returns:
        The validated URL.

    Raises:
        PypiError: If the URL is not https or lacks a hostname.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PypiError(f"refusing to fetch non-HTTPS index URL: {url!r}")
    return url


def fetch_package_json(
    name: str,
    timeout: float = TIMEOUT_SECONDS,
    url_template: str = PYPI_URL,
) -> dict:  # type: ignore[type-arg]
    """Fetch and parse a package index's JSON metadata for a package.

    Args:
        name: The PyPI package name.
        timeout: Request timeout in seconds.
        url_template: JSON API URL with a ``{name}`` placeholder. Defaults to
            pypi.org; custom (private index) templates must be HTTPS.

    Returns:
        Parsed JSON payload as a dict.

    Raises:
        PypiError: On network failure or invalid response.
    """
    safe_name = validate_name(name)
    url = url_template.format(name=safe_name)
    if url_template == PYPI_URL:
        validate_pypi_url(url)
    else:
        validate_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # nosec B310
            raw = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise PypiError(f"pypi fetch failed for {safe_name}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PypiError(f"pypi json parse failed for {safe_name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PypiError(f"pypi response for {safe_name} is not a JSON object")
    return payload


def _is_yanked_release(files: object) -> bool:
    """Return True if all release files are marked yanked.

    PyPI yanks a release by yanking every file in it; a release with a mix of
    yanked and non-yanked files is still installable.

    Args:
        files: The release file list from PyPI JSON.

    Returns:
        True if the release is yanked.
    """
    if not isinstance(files, list):
        return False
    dict_files = [f for f in files if isinstance(f, dict)]
    if not dict_files:
        return False
    return all(f.get("yanked", False) for f in dict_files)


# lite: end pypi-fetch


def parse_version_detail(
    payload: dict,  # type: ignore[type-arg]
    current_version: str,
    include_prereleases: bool = False,
) -> VersionDetail:
    """Extract full version detail from a PyPI JSON payload.

    Args:
        payload: The parsed PyPI JSON payload.
        current_version: The currently installed version (used for yanked detection).
        include_prereleases: Whether to treat prereleases as upgrade candidates.

    Returns:
        A VersionDetail with all fields populated.

    Raises:
        PypiError: If the payload is malformed.
    """
    info = payload.get("info") or {}
    latest_field = info.get("version")
    if not isinstance(latest_field, str) or not latest_field:
        raise PypiError("pypi payload missing info.version")

    releases = payload.get("releases") or {}

    # Check if current version is yanked
    current_files = releases.get(current_version) or []
    is_yanked = _is_yanked_release(current_files)

    # Collect stable and prerelease candidates, keeping the raw release key
    # alongside the parsed Version: `releases` is keyed by the exact string
    # PyPI serves, which may differ from the normalized str(Version) form.
    stable_candidates: list[tuple[Version, str]] = []
    prerelease_candidates: list[tuple[Version, str]] = []

    for v_str, files in releases.items():
        if not isinstance(v_str, str):
            continue
        # Skip yanked releases
        if _is_yanked_release(files):
            continue
        try:
            v = parse_version(v_str)
        except InvalidVersion:
            continue
        if v.is_devrelease:
            continue  # skip dev releases
        if v.is_prerelease:
            prerelease_candidates.append((v, v_str))
        else:
            stable_candidates.append((v, v_str))

    def _newest(candidates: list[tuple[Version, str]]) -> tuple[Version, str]:
        return max(candidates, key=lambda pair: pair[0])

    latest_stable: str | None = _newest(stable_candidates)[1] if stable_candidates else None

    # Determine effective latest for upgrade comparison
    effective: tuple[Version, str] | None = None
    if include_prereleases and prerelease_candidates:
        effective = _newest(stable_candidates + prerelease_candidates)
    elif stable_candidates:
        effective = _newest(stable_candidates)

    effective_latest = effective[1] if effective else latest_field
    is_prerelease = bool(effective and effective[0].is_prerelease)
    is_dev = bool(effective and effective[0].is_devrelease)

    # Extract published timestamp for the effective latest
    latest_files = releases.get(effective_latest) or []
    published: datetime | None = None
    if isinstance(latest_files, list) and latest_files:
        timestamps: list[datetime] = []
        for file_info in latest_files:
            if not isinstance(file_info, dict):
                continue
            iso = file_info.get("upload_time_iso_8601") or file_info.get("upload_time")
            if not isinstance(iso, str):
                continue
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps.append(dt)
        if timestamps:
            published = min(timestamps)

    return VersionDetail(
        latest=effective_latest,
        published=published,
        latest_stable=latest_stable,
        is_prerelease=is_prerelease,
        is_yanked=is_yanked,
        is_dev=is_dev,
    )


def get_version_detail(
    name: str,
    current_version: str,
    include_prereleases: bool = False,
    timeout: float = TIMEOUT_SECONDS,
    url_template: str = PYPI_URL,
) -> VersionDetail:
    """Fetch and parse full version detail for a package from PyPI.

    Args:
        name: The PyPI package name.
        current_version: Currently installed version (for yanked detection).
        include_prereleases: Whether to consider pre-releases as upgrades.
        timeout: Request timeout in seconds.
        url_template: JSON API URL template (see fetch_package_json).

    Returns:
        A VersionDetail with all fields populated.

    Raises:
        PypiError: On network failure or malformed response.
    """
    payload = fetch_package_json(name, timeout=timeout, url_template=url_template)
    return parse_version_detail(payload, current_version, include_prereleases=include_prereleases)


def get_latest(name: str, timeout: float = TIMEOUT_SECONDS) -> tuple[str, datetime | None]:
    """Convenience: fetch latest version and publish time for a package.

    Args:
        name: The PyPI package name.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (latest_version_string, publish_datetime_or_None).

    Raises:
        PypiError: On network failure or malformed response.
    """
    detail = get_version_detail(name, current_version="0.0.0", timeout=timeout)
    return detail.latest, detail.published


__all__ = [
    "PYPI_URL",
    "PypiError",
    "VersionDetail",
    "fetch_package_json",
    "get_latest",
    "get_version_detail",
    "validate_https_url",
    "validate_name",
    "validate_pypi_url",
]
