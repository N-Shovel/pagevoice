"""Status line: show plan usage, and save it for the usage guard hook.

Claude Code passes session data to the status line as JSON on stdin. For claude.ai Pro
and Max plans that data includes `rate_limits`: the 5-hour and 7-day windows, each with
the percent used and the reset time. Hooks never receive these numbers, so this script
prints a one-line summary and saves them to a small state file that
`.claude/hooks/usage_guard.py` reads.

The state file is in the system temp folder because the limits belong to the account,
not to one project. Set CLAUDE_USAGE_STATE_DIR to put it somewhere else (the tests do).
"""

import contextlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

WINDOWS = {"five_hour": "5h", "seven_day": "week"}


def state_path() -> Path:
    folder = os.environ.get("CLAUDE_USAGE_STATE_DIR") or os.path.join(
        tempfile.gettempdir(), "claude-usage"
    )
    return Path(folder) / "usage.json"


def number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def read_windows(limits: dict) -> dict:
    windows = {}
    for name in WINDOWS:
        window = limits.get(name) or {}
        used, resets = window.get("used_percentage"), window.get("resets_at")
        if number(used) and number(resets):
            windows[name] = {"used_percentage": float(used), "resets_at": int(resets)}
    return windows


def save(windows: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"usage.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps({"updated_at": int(time.time()), "windows": windows}), encoding="utf-8"
    )
    os.replace(tmp, path)  # atomic, so the hook never reads half a file


def clock(epoch: int) -> str:
    when = datetime.fromtimestamp(epoch)
    if when.date() == datetime.now().date():
        return when.strftime("%H:%M")
    return when.strftime("%a %H:%M")


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}

    parts = []
    model = (data.get("model") or {}).get("display_name")
    if model:
        parts.append(str(model))

    limits = data.get("rate_limits")
    if isinstance(limits, dict):
        # Only overwrite when Claude Code sent rate_limits at all. Before a session's
        # first reply it sends none, and the last saved numbers are still the best guess.
        windows = read_windows(limits)
        with contextlib.suppress(OSError):  # a temp-folder problem must not break the line
            save(windows)
        for name, label in WINDOWS.items():
            if name in windows:
                used = windows[name]["used_percentage"]
                parts.append(f"{label} {used:.0f}% (resets {clock(windows[name]['resets_at'])})")

    context = (data.get("context_window") or {}).get("used_percentage")
    if number(context):
        parts.append(f"context {context:.0f}%")

    print(" | ".join(parts) if parts else "usage: waiting for the first reply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
