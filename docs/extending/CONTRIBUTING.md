# Contributing

Thank you for considering a contribution to **do_i_need_to_upgrade**!

## Development setup

```bash
git clone https://github.com/matthewdeanmartin/do_i_need_to_upgrade
cd do_i_need_to_upgrade
uv sync
uv run pre-commit install
```

## Running the quality gate

```bash
uv run make check
```

Individual targets:

```bash
uv run make lint        # ruff + pylint
uv run make typecheck   # mypy strict
uv run make test        # pytest with coverage
uv run make security    # bandit + pip-audit
uv run make smoke       # CLI smoke checks
```

## Code style

- Line length: 120
- Type annotations required on all public functions
- Google-style docstrings
- No bare `python`, `pip`, or `pytest` — always use `uv run`

## Pull requests

1. Fork the repository and create a feature branch.
2. Run `uv run make check` — all checks must pass.
3. Open a pull request against `main`.
4. Update `CHANGELOG.md` under `[Unreleased]`.
