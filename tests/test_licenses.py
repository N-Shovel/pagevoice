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
        # The Lesser GPL is fine, any version.
        ("GNU Lesser General Public License v2 (LGPLv2)", "ok"),
        ("LGPL-2.0-only", "ok"),
        ("LGPL-2.1-only", "ok"),
        ("GNU General Public License v2 or later (GPLv2+)", "ok"),
        ("GPL-2.0+", "ok"),
        # Bare SPDX "GPL-2.0" / "GPL-2" mean 2.0-only.
        ("GPL-2.0", "deny"),
        ("GPL-2", "deny"),
        # AND: every part must pass, and "or later" elsewhere doesn't rescue it.
        ("GPL-2.0-only AND LGPL-2.1-or-later", "deny"),
        ("MIT AND BSD-3-Clause", "ok"),
        ("", "unknown"),
        ("Some Custom License", "unknown"),
    ],
)
def test_verdicts(license_, expected):
    assert check.verdict(license_) == expected
