# tkinter_component

This note is for app authors who want `do_i_need_to_upgrade` to show update information inside a Tkinter app, not only through stderr / terminal text.

## Core idea

Keep `do_i_need_to_upgrade` itself UI-agnostic.

The library should continue to return `Report` objects and render plain text well. A Tkinter app should add a small host-local adapter that decides:

- whether to show a popup, banner, status text, or tray-style hint
- when to show it
- whether terminal output should still happen too

That keeps the core package lightweight and lets each app match its own UI tone.

## Recommended architecture

Do not make the core package import Tkinter.

Instead:

1. Use `check_for_updates(...)` or the integrate helpers to get a `Report`.
1. In the host app, convert that report into Tkinter behavior.
1. Keep stderr output as the fallback/default path.

Host-local module example:

```python
from do_i_need_to_upgrade.api import check_for_updates
from do_i_need_to_upgrade.settings import Settings


def settings() -> Settings:
    return Settings(dist_name="my_app", position="start", notify="return-only")


def startup_report():
    report = check_for_updates(settings=settings())
    return report if not report.is_empty else None


def exit_report():
    report = check_for_updates(settings=settings().replace(allow_network=False, notify="return-only"))
    return report if not report.is_empty else None
```

Then add a Tkinter-specific presenter in the host app.

## Best default: schedule onto the event loop

Do not show a dialog before the root window exists.

Do not block window construction with a modal popup during initialization.

Instead, once the main window is built, schedule the notice:

```python
def schedule_tk_notice(root, text: str) -> None:
    from tkinter import messagebox

    if not text:
        return

    def show_notice() -> None:
        messagebox.showinfo("Update available", text, parent=root)

    root.after(250, show_notice)
```

Why this is the safest default:

- the root window exists
- focus behavior is more predictable
- the app can finish painting first
- test code can patch `root.after(...)` and `messagebox.showinfo(...)`

## Modal popup vs non-modal UI

### Modal popup

Good for:

- infrequent notices
- developer tools
- apps where updates are important enough to interrupt

Tradeoffs:

- interrupts first-use flow
- can feel naggy
- awkward if shown every launch

### Status bar or banner

Good for:

- frequent app launches
- low-friction reminders
- apps that already have a status area

Tradeoffs:

- easier to miss
- requires a little app-specific widget work

### Recommended compromise

Use both of these:

- stderr notice immediately
- optional in-app Tkinter notice when the app has a real GUI shell

That gives terminal visibility for logs and shell launches, while still helping GUI-only users.

## Suggested host API

For Tkinter apps, a small host-local helper module is enough:

```python
def render_notice(report) -> str:
    ...


def schedule_tk_notice(root, report) -> None:
    ...
```

Where:

- `render_notice(report)` returns the same text you would print to stderr
- `schedule_tk_notice(root, report)` decides whether and how to show a GUI notice

This keeps the host app in control of presentation.

## Startup / exit behavior

For long-running Tkinter apps:

1. Run the cached/background check at startup.
1. Print the startup text to stderr if non-empty.
1. Schedule an optional Tk notice from the startup report.
1. Let the app run so the background refresh can update the cache.
1. On exit, do a cache-only reread.
1. Print the exit text to stderr if it is non-empty and different from the startup notice.

The Tk dialog is usually only needed on startup.

Exit-time GUI dialogs are usually a bad idea because:

- the user is already closing the app
- the root may be tearing down
- focus and modality get messy during shutdown

## If an app wants a less annoying GUI

Prefer one of these over a modal popup:

- a dismissible top-of-window banner
- a status bar message with a "Details" button
- a Help/About menu item that opens the last update report
- a small "Update available" badge in the toolbar

These patterns are better for end-user apps than forcing a popup every launch.

## What an LLM should implement first

If asked to add Tkinter support to an existing app, do this in order:

1. Get terminal/stderr integration working first.
1. Add a host-local helper such as `upgrade_integration.py`.
1. Add `schedule_tk_notice(root, report)` in that helper.
1. Call it only after the main window has been created.
1. Add tests that patch `root.after` and `messagebox.showinfo`.

Do not start by editing the core library to import Tkinter directly.

## Real example

`C:\github\gui4aws\gui4aws\upgrade_integration.py`

That repo now demonstrates:

- runtime dependency wiring
- integrated `upgrade` and `check-updates` subcommands
- stderr notices
- scheduled Tkinter popup notice on launch
