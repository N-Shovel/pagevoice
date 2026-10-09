"""The protect_files hook must keep Claude away from golden answers and checksums."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "protect_files.py"


def run_hook(tool_name: str, tool_input: dict) -> int:
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True
    ).returncode


@pytest.mark.parametrize(
    "path",
    [
        "tests/corpus/public/moby-dick/expected/page-012.txt",
        "tests/corpus/private/some-novel/expected/page-003.txt",
        str(ROOT / "tests" / "corpus" / "public" / "x" / "expected" / "p1.txt"),
        "src/pagevoice/voice/model_manifest.json",
        "tests/voice/sentences.tsv",
    ],
)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_blocks_writes_to_protected_files(tool, path):
    assert run_hook(tool, {"file_path": path}) == 2


@pytest.mark.parametrize(
    "path",
    [
        "tests/corpus/public/moby-dick/candidate/page-012.txt",
        "src/pagevoice/voice/model_manifest.proposed.json",
        "tests/voice/sentences.proposed.tsv",
        "src/pagevoice/cli.py",
    ],
)
def test_allows_other_files(path):
    assert run_hook("Write", {"file_path": path}) == 0


@pytest.mark.parametrize(
    "command",
    [
        "sed -i 's/a/b/' tests/corpus/public/x/expected/p1.txt",
        "echo hi > tests/corpus/public/x/expected/p1.txt",
        "cp new.txt tests\\corpus\\public\\x\\expected\\p1.txt",
        "git checkout -- tests/corpus/public/x/expected/",
        "Set-Content tests/voice/sentences.tsv 'x'",
        "python -c \"open('src/pagevoice/voice/model_manifest.json','w')\"",
    ],
)
def test_blocks_shell_writes(command):
    assert run_hook("Bash", {"command": command}) == 2


@pytest.mark.parametrize(
    "command",
    [
        "cat tests/corpus/public/x/expected/p1.txt",
        "git diff tests/corpus/public/x/expected/",
        "uv run pytest tests",
        "git status",
        "uv run python tools/roundtrip.py",
        "uv run python tools/benchmark.py --variants fp32 int8",
    ],
)
def test_allows_reading_shell_commands(command):
    assert run_hook("Bash", {"command": command}) == 0


def test_tools_must_not_take_the_sentence_list_path():
    # Known limitation: the guard can't tell a read from a write when python names a
    # protected file, so tools/benchmark.py and tools/roundtrip.py read it by default.
    command = "uv run python tools/roundtrip.py --sentences tests/voice/sentences.tsv"
    assert run_hook("Bash", {"command": command}) == 2
