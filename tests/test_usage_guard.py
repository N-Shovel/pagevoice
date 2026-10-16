"""The usage status line and guard pause Claude near the plan limit, and stay quiet otherwise."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / ".claude" / "hooks"
GUARD = HOOKS / "usage_guard.py"
STATUSLINE = HOOKS / "usage_statusline.py"
HOUR = 3600


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_USAGE_STATE_DIR", str(tmp_path))
    return tmp_path


def run(script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def write_usage(state_dir: Path, used: float, resets_at: int | None = None, window="five_hour"):
    if resets_at is None:
        resets_at = int(time.time()) + HOUR
    windows = {window: {"used_percentage": used, "resets_at": resets_at}}
    (state_dir / "usage.json").write_text(json.dumps({"windows": windows}), encoding="utf-8")


def note(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return ""
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def post_tool_use(state_dir) -> str:
    return note(run(GUARD, {"hook_event_name": "PostToolUse", "tool_name": "Bash"}))


def user_prompt(state_dir) -> str:
    return note(run(GUARD, {"hook_event_name": "UserPromptSubmit", "prompt": "continue"}))


def test_quiet_without_usage_data(state_dir):
    assert post_tool_use(state_dir) == ""
    assert user_prompt(state_dir) == ""


def test_quiet_below_threshold(state_dir):
    write_usage(state_dir, 89.9)
    assert post_tool_use(state_dir) == ""
    assert user_prompt(state_dir) == ""


def test_quiet_after_the_window_resets(state_dir):
    write_usage(state_dir, 99, resets_at=int(time.time()) - 60)
    assert post_tool_use(state_dir) == ""
    assert user_prompt(state_dir) == ""


def test_pause_note_once_per_level(state_dir):
    resets = int(time.time()) + HOUR
    write_usage(state_dir, 91, resets)
    first = post_tool_use(state_dir)
    assert "5-hour limit at 91%" in first
    assert "docs/PROGRESS.md" in first
    assert post_tool_use(state_dir) == ""  # no repeat after every tool call

    write_usage(state_dir, 96, resets)  # same window, next level
    assert "at 96%" in post_tool_use(state_dir)
    assert post_tool_use(state_dir) == ""


def test_new_window_reminds_again(state_dir):
    write_usage(state_dir, 91, int(time.time()) + HOUR)
    assert post_tool_use(state_dir)
    write_usage(state_dir, 91, int(time.time()) + 6 * HOUR)
    assert post_tool_use(state_dir)


def test_weekly_limit_counts_too(state_dir):
    write_usage(state_dir, 93, int(time.time()) + 3 * 24 * HOUR, window="seven_day")
    assert "weekly limit at 93%" in post_tool_use(state_dir)


def test_continue_before_reset_is_answered_every_time(state_dir):
    write_usage(state_dir, 92)
    assert "continue anyway" in user_prompt(state_dir)
    assert "continue anyway" in user_prompt(state_dir)


def test_broken_state_file_is_ignored(state_dir):
    (state_dir / "usage.json").write_text("{not json", encoding="utf-8")
    assert post_tool_use(state_dir) == ""


def test_statusline_saves_rate_limits(state_dir):
    resets = int(time.time()) + HOUR
    result = run(
        STATUSLINE,
        {
            "model": {"display_name": "Opus"},
            "rate_limits": {"five_hour": {"used_percentage": 42.4, "resets_at": resets}},
            "context_window": {"used_percentage": 35},
        },
    )
    assert result.returncode == 0, result.stderr
    assert "5h 42%" in result.stdout
    assert "context 35%" in result.stdout
    saved = json.loads((state_dir / "usage.json").read_text(encoding="utf-8"))
    assert saved["windows"]["five_hour"] == {"used_percentage": 42.4, "resets_at": resets}


def test_statusline_keeps_last_numbers_before_first_reply(state_dir):
    write_usage(state_dir, 91)
    before = (state_dir / "usage.json").read_text(encoding="utf-8")
    result = run(STATUSLINE, {"model": {"display_name": "Opus"}})
    assert result.returncode == 0, result.stderr
    assert (state_dir / "usage.json").read_text(encoding="utf-8") == before


def test_statusline_survives_bad_input(state_dir):
    result = subprocess.run(
        [sys.executable, str(STATUSLINE)], input="not json", capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.strip()
