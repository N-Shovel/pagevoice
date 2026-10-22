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
# GPL version 2 *only* can't be combined with a GPL-3.0 program. "or later" is fine.
GPL2_ONLY = re.compile(
    r"gpl-?2(\.0)?-only|gplv2(?!\+)|\bv2 \(gplv2\)|general public license,? v(ersion )?2\b",
    re.IGNORECASE,
)
OR_LATER = re.compile(r"or[- ]later|\+|v2 or later", re.IGNORECASE)
GPL2_ONLY_WARNING = "GPL-2.0-only can't be combined with GPL-3.0"


def verdict(license_: str) -> str:
    """'ok', 'deny' or 'unknown' for one package's license text.

    "A OR B" offers a choice: the package is fine if any one alternative is."""
    if DENY.search(license_):
        return "deny"
    choices = [c.strip() for c in re.split(r"\s+OR\s+|;", license_) if c.strip()]
    results = []
    for choice in choices or [license_]:
        if GPL2_ONLY.search(choice) and not OR_LATER.search(choice):
            results.append("gpl2-only")
        elif ALLOW.search(choice):
            results.append("ok")
        else:
            results.append("unknown")
    if "ok" in results:
        return "ok"
    if all(r == "gpl2-only" for r in results):
        return "deny"
    return "unknown"


# Packages whose metadata is missing or misleading, checked by hand. Every entry here
# must also have a row in the dependency log in docs/DECISIONS.md.
REVIEWED: dict[str, str] = {
    # PyPI metadata is empty. The repo LICENSE is MIT; it bundles espeak-ng (GPL-3.0+).
    "espeakng-loader": "MIT (bundles espeak-ng, GPL-3.0-or-later)",
    # Build tool (the "build" group). Classifier says "GPLv2"; the real terms (COPYING.txt
    # and PyPI's license field) are GPL-2.0-or-later plus the bootloader exception, which
    # allows shipping its launcher with any program. Reviewed 2026-10-22.
    "pyinstaller": "GPL-2.0-or-later WITH Bootloader-exception",
    "pyinstaller-hooks-contrib": "GPL-2.0-or-later OR Apache-2.0 (runtime hooks Apache-2.0)",
}
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
        result = verdict(license_)
        if result == "deny":
            why = f" ({GPL2_ONLY_WARNING})" if GPL2_ONLY.search(license_) else ""
            problems.append(f"  NOT ALLOWED  {name} {version}: {license_}{why}")
        elif result == "unknown":
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
