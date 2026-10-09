"""PostToolUse: format and lint the Python file Claude just wrote.

Runs `ruff format`, then `ruff check --fix`, on that one file. Problems ruff can't fix
are printed with exit code 2, which shows them to Claude so it fixes them right away.
Unused imports and variables are reported but never auto-removed, because Claude often
adds an import one edit before the code that uses it.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input") or {}
    path_str = tool_input.get("file_path") or (payload.get("tool_response") or {}).get("filePath")
    if not path_str:
        return 0
    path = Path(path_str)
    if not path.is_absolute():
        path = ROOT / path
    if path.suffix not in {".py", ".pyi"} or not path.is_file():
        return 0
    try:
        rel = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return 0  # outside the repo

    fmt = ruff("format", "--quiet", rel)
    if "No module named ruff" in fmt.stderr:
        print("ruff is not installed in the project environment. Run: uv sync", file=sys.stderr)
        return 1

    check = ruff("check", "--fix", "--unfixable", "F401,F841", "--output-format", "concise", rel)
    if check.returncode != 0:
        sys.stderr.write(f"ruff found problems in {rel}:\n{check.stdout}{fmt.stderr}{check.stderr}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
