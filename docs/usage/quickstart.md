# Quick Start

## As a standalone CLI

```bash
# Check if do_i_need_to_upgrade itself needs upgrading
do_i_need_to_upgrade check

# Show cached state (no network)
do_i_need_to_upgrade status

# Vulnerability audit
do_i_need_to_upgrade audit

# Self-upgrade
do_i_need_to_upgrade upgrade --dry-run
do_i_need_to_upgrade upgrade

# Snooze a specific version for 30 days
do_i_need_to_upgrade snooze do_i_need_to_upgrade==0.1.0 --days 30

# Verify installed packages satisfy their declared dependencies
do_i_need_to_upgrade integrity-check

# Clear the cache
do_i_need_to_upgrade clear-cache
```

## Embedding in your app (two lines)

```python
from pathlib import Path
from do_i_need_to_upgrade import check_for_updates, GenericHost

# One-liner: background check with atexit notification
check_for_updates(
    host=GenericHost(
        dist_name="my-awesome-app",
        cache_dir=Path.home() / ".cache" / "my-awesome-app" / "updates",
    ),
    position="start",  # zero-cost background check
)
```

When the program exits, if there's a newer version, your user sees:

```
[update] my-awesome-app 1.0.0 -> 2.0.0 is available
```

## Embed with synchronous check (at program end)

```python
check_for_updates(host=host, position="end")
# This refreshes PyPI synchronously so the next start is instant.
```

## Check with JSON output

```bash
do_i_need_to_upgrade check --json | jq .
```
