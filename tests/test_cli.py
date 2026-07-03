"""Smoke tests for the CLI entry point."""


def test_import() -> None:
    """Package can be imported."""
    import do_i_need_to_upgrade  # noqa: F401


def test_version() -> None:
    """Package exposes a version string."""
    from do_i_need_to_upgrade.__about__ import __version__

    assert isinstance(__version__, str)
    assert __version__
