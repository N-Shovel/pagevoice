"""The license checker (tools/check_licenses.py) decides what PageVoice may ship."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_licenses", Path(__file__).resolve().parents[1] / "tools" / "check_licenses.py"
)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.mark.parametrize(
    ("license_", "expected"),
    [
        ("MIT", "ok"),
        ("GPL-3.0-or-later", "ok"),
        ("GPL-2.0-or-later", "ok"),
        ("GNU General Public License v3 or later (GPLv3+)", "ok"),
        ("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", "ok"),  # a choice: LGPL-3.0 works
        ("GPL-2.0-only", "deny"),
        ("GNU General Public License v2 (GPLv2)", "deny"),
        ("AGPL-3.0", "deny"),
        ("Creative Commons Non-Commercial", "deny"),
        ("", "unknown"),
        ("Some Custom License", "unknown"),
    ],
)
def test_verdicts(license_, expected):
    assert check.verdict(license_) == expected
