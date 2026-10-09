"""Fail if any installed package has a license PageVoice can't ship under GPL-3.0.

Checks every package in the current environment, including transitive dependencies.

    uv run python tools/check_licenses.py

To vet a package before it touches the project, run the same check in a throwaway
environment that holds only that package and its dependencies:

    uv run --isolated --no-project --with <pkg> --with pip-licenses python tools/check_licenses.py
"""

import json
import re
import subprocess
import sys

# Checked first: anything matching here fails, even if it also matches ALLOW.
DENY = re.compile(
    r"affero|agpl|non[- ]?commercial|cc-by-nc|proprietary|commercial|sspl|"
    r"business source|busl|elastic license",
    re.IGNORECASE,
)
# Licenses compatible with distributing the app under GPL-3.0.
ALLOW = re.compile(
    r"\bmit\b|\bbsd\b|0bsd|apache|\bisc\b|\bpsf\b|python software foundation|"
    r"\bmpl\b|mozilla public|\blgpl|lesser general public|\bgpl|general public license|"
    r"unlicense|zlib|\bhpnd\b|cc0|public domain|bsl-1\.0|boost software",
    re.IGNORECASE,
)
# Packages whose metadata is missing or misleading, checked by hand. Every entry here
# must also have a row in the dependency log in docs/DECISIONS.md.
REVIEWED: dict[str, str] = {}
# This project itself (GPL-3.0).
SELF = {"pagevoice"}


def main() -> int:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "piplicenses", "--from=mixed", "--format=json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except subprocess.CalledProcessError:
        print("pip-licenses is not installed here. Run: uv sync", file=sys.stderr)
        return 2

    packages = json.loads(result.stdout)
    problems: list[str] = []
    for pkg in sorted(packages, key=lambda p: p["Name"].lower()):
        name, version, license_ = pkg["Name"], pkg["Version"], pkg["License"].strip()
        key = name.lower()
        if key in SELF or key in REVIEWED:
            continue
        if DENY.search(license_):
            problems.append(f"  NOT ALLOWED  {name} {version}: {license_}")
        elif not ALLOW.search(license_):
            problems.append(
                f"  UNKNOWN      {name} {version}: {license_ or '(no license metadata)'}"
            )

    if problems:
        print(f"License check failed for {len(problems)} of {len(packages)} packages:")
        print("\n".join(problems))
        print(
            "\nAGPL, non-commercial and unknown licenses can't ship in PageVoice. For an UNKNOWN,"
            "\ncheck the real license by hand; if it is fine, add it to REVIEWED in this script"
            "\nand to the dependency log in docs/DECISIONS.md."
        )
        return 1

    print(f"License check passed: {len(packages)} packages, all GPL-3.0 compatible.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
