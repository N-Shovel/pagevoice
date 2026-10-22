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
# GPL version 2 *only* can't be combined with a GPL-3.0 program; "or later" is fine.
# Not the LGPL: an "L" or "Lesser" in front means the Lesser GPL, which is compatible.
# A bare "GPL-2.0"/"GPL-2" is the old SPDX name for 2.0-only.
GPL2_ONLY = re.compile(
    r"(?<![l\w])gpl-?2(\.0)?(-only)?\b(?![-.]?\d|\s*\+|-or-later)"
    r"|(?<![l\w])gplv2\b(?!\s*\+)"
    r"|(?<!lesser )(?<!library )general public license,? v(ersion )?2\b(?!\.1|\s*\+| or later)",
    re.IGNORECASE,
)
GPL2_ONLY_WARNING = "GPL-2.0-only can't be combined with GPL-3.0"


def _part(text: str) -> str:
    """One licence of an AND expression: 'gpl2-only', 'ok' or 'unknown'."""
    if GPL2_ONLY.search(text):
        return "gpl2-only"
    return "ok" if ALLOW.search(text) else "unknown"


def verdict(license_: str) -> str:
    """'ok', 'deny' or 'unknown' for one package's license text.

    "A OR B" offers a choice: fine if any one alternative is. "A AND B" applies both:
    fine only if every part is."""
    if DENY.search(license_):
        return "deny"
    choices = [c.strip() for c in re.split(r"\s+OR\s+|;", license_) if c.strip()]
    results = []
    for choice in choices or [license_]:
        parts = [_part(p) for p in re.split(r"\s+AND\s+", choice) if p.strip()]
        if "gpl2-only" in parts:
            results.append("gpl2-only")
        elif parts and all(r == "ok" for r in parts):
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
    # Runtime (misaki, phonemizer-fork). New code Apache-2.0; parts derived from Python's
    # own regex engine under CNRI-Python, the Python 1.6.1 licence that CNRI amended to be
    # GPL-compatible (FSF lists it as compatible). Reviewed 2026-10-22.
    "regex": "Apache-2.0 AND CNRI-Python (Python 1.6.1 licence, GPL-compatible)",
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
