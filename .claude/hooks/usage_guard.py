"""Usage guard: tell Claude to write up its progress and pause near the plan's usage limit.

Hooks don't receive plan usage, so the status line (`usage_statusline.py`) saves it to a
small state file after every reply. This hook reads that file and, when the 5-hour or
weekly limit is at THRESHOLD percent or more and hasn't reset yet, adds a note for Claude:

- UserPromptSubmit: on every prompt. If the owner says "continue" before the reset,
  Claude can tell him the reset time instead of starting work.
- PostToolUse: once per limit window at each level in REMIND_AT, so Claude stops
  starting new work without the note repeating after every tool call.

What Claude does with the note is in docs/PAUSE_AND_RESUME.md. With no state file, no
rate-limit data (an API-key sign-in) or a window past its reset time, the hook says
nothing. It never blocks anything.
"""

import contextlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

THRESHOLD = 90
REMIND_AT = (90, 95)
NAMES = {"five_hour": "5-hour limit", "seven_day": "weekly limit"}


def state_dir() -> Path:
    return Path(
        os.environ.get("CLAUDE_USAGE_STATE_DIR")
        or os.path.join(tempfile.gettempdir(), "claude-usage")
    )


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def over_threshold(now: float) -> dict:
    """Windows at THRESHOLD or more whose reset time is still ahead."""
    windows = read_json(state_dir() / "usage.json").get("windows") or {}
    hot = {}
    for name, window in windows.items():
        if name not in NAMES or not isinstance(window, dict):
            continue
        used, resets = window.get("used_percentage"), window.get("resets_at")
        if not isinstance(used, int | float) or not isinstance(resets, int | float):
            continue
        if used >= THRESHOLD and resets > now:
            hot[name] = {"used_percentage": float(used), "resets_at": int(resets)}
    return hot


def clock(epoch: int) -> str:
    when = datetime.fromtimestamp(epoch)
    if when.date() == datetime.now().date():
        return when.strftime("%H:%M")
    return when.strftime("%a %d %b %H:%M")


def describe(hot: dict) -> tuple[str, str]:
    parts = [
        f"{NAMES[name]} at {w['used_percentage']:.0f}% (resets {clock(w['resets_at'])})"
        for name, w in hot.items()
    ]
    resume_at = clock(max(w["resets_at"] for w in hot.values()))
    return "; ".join(parts), resume_at


def new_reminder_due(hot: dict) -> bool:
    """True if some window reached a REMIND_AT level it hasn't been reminded at yet."""
    path = state_dir() / "reminded.json"
    reminded = read_json(path)
    due = False
    for name, w in hot.items():
        key = f"{name}:{w['resets_at']}"
        level = max(level for level in REMIND_AT if w["used_percentage"] >= level)
        if reminded.get(key, 0) < level:
            reminded[key] = level
            due = True
    if due:
        with contextlib.suppress(OSError):
            path.write_text(json.dumps(reminded), encoding="utf-8")
    return due


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    event = payload.get("hook_event_name", "")

    hot = over_threshold(time.time())
    if not hot:
        return 0

    usage, resume_at = describe(hot)
    if event == "UserPromptSubmit":
        note = (
            f'Plan usage: {usage}. It hasn\'t reset yet. If the owner only said "continue", '
            f"tell him in one line that it resets at {resume_at} and wait; go on only if he "
            'says "continue anyway". See docs/PAUSE_AND_RESUME.md.'
        )
    elif event == "PostToolUse":
        if not new_reminder_due(hot):
            return 0
        note = (
            f"Plan usage: {usage}. Pause now as docs/PAUSE_AND_RESUME.md says: start nothing "
            "new, run the fast tests, commit to the current branch, update "
            "docs/PROGRESS.md, push the branch (never main), then stop and tell the owner "
            'to say "continue" after '
            f"{resume_at}."
        )
    else:
        return 0

    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": note}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
