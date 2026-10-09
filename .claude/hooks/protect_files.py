"""PreToolUse guard: Claude may not change golden answers or pinned checksums.

The easiest way to make a failing test pass is to change the expected answer, so these
files are changed by a human only. Exit code 2 blocks the tool call and shows the
message to Claude.

For shell commands this is a tripwire, not a sandbox: it blocks commands that name a
protected file and look like they write to it.
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROTECTED_FILES = {
    "src/pagevoice/voice/model_manifest.json": (
        "the pinned model download URLs and SHA-256 checksums",
        "src/pagevoice/voice/model_manifest.proposed.json",
    ),
    "tests/voice/sentences.tsv": (
        "the fixed voice sentence list and its expected spoken forms",
        "tests/voice/sentences.proposed.tsv",
    ),
}
GOLDEN = re.compile(r"^tests/corpus/.+/expected(/|$)")

FILE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
SHELL_WRITES = re.compile(
    r">|\btee\b|\bsed\b|\bperl\b|\bawk\b|\bmv\b|\bcp\b|\brm\b|\bdel\b|\btruncate\b|"
    r"\btouch\b|\bdd\b|\bpython[0-9.]*\b|\bpy\b|\bnode\b|"
    r"\bgit\s+(checkout|restore|reset|rm|mv|apply|stash|clean)\b|"
    r"set-content|add-content|out-file|clear-content|remove-item|move-item|copy-item|"
    r"new-item|rename-item|\[io\.file\]",
    re.IGNORECASE,
)


def project_relative(path_str: str) -> str | None:
    """Return the path relative to the repo root in posix form, or None if outside it."""
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    try:
        rel = os.path.relpath(os.path.abspath(path), ROOT)
    except ValueError:  # different drive on Windows
        return None
    rel = rel.replace("\\", "/")
    if os.name == "nt":
        rel = rel.lower()
    return None if rel.startswith("../") else rel


def block(message: str) -> None:
    sys.stderr.write(f"Blocked by .claude/hooks/protect_files.py: {message}\n")
    sys.exit(2)


def check_file(rel: str) -> None:
    for protected, (what, proposed) in PROTECTED_FILES.items():
        if rel == protected:
            block(
                f"{rel} holds {what}. Only a human changes it. If it is truly wrong, write "
                f"your version to {proposed} and ask the user to review it and move it in."
            )
    if GOLDEN.match(rel):
        block(
            f"{rel} is a hand-checked golden answer. Only a human changes it. Fix the code, "
            "not the expectation. If the expectation itself is wrong, write your version to "
            "the book's candidate/ folder and ask the user to review it and move it in."
        )


def check_command(command: str) -> None:
    text = command.replace("\\", "/").lower()
    names_golden = "corpus" in text and "expected" in text
    names_file = any(Path(p).name in text for p in PROTECTED_FILES)
    if (names_golden or names_file) and SHELL_WRITES.search(text):
        block(
            "this command names a protected file (golden answers in tests/corpus/*/expected/, "
            "the model manifest, or the voice sentence list) and looks like it writes to it. "
            "Use the Read tool to look at them. Only a human changes them."
        )


def main() -> int:
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool in FILE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        rel = project_relative(path) if path else None
        if rel:
            check_file(rel)
    elif tool in SHELL_TOOLS:
        check_command(tool_input.get("command", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
