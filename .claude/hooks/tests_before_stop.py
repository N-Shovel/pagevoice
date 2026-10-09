"""Stop hook: Claude can't call a task done while the fast tests fail.

Runs `pytest -m "not slow" -q`. On failure, exit code 2 shows the failures to Claude and
makes it keep working. If Claude is already continuing because of this hook
(`stop_hook_active`), the stop is let through, so a test Claude can't fix doesn't loop
forever. Claude must then tell the user plainly which tests fail.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NO_TESTS_COLLECTED = 5


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("stop_hook_active"):
        return 0

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not slow",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return 0

    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-40:])
    if result.returncode == NO_TESTS_COLLECTED:
        # The repo always has fast tests, so collecting none means discovery broke.
        problem = "pytest collected no fast tests (test discovery is broken)"
    else:
        problem = "Fast tests are failing"
    sys.stderr.write(
        f"{problem}, so the task isn't done. Fix it, or if you can't, tell the user plainly "
        "what fails and why.\n\n" + tail + "\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
