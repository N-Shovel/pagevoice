"""The packaged-build self-test (M5): its report, and which failures may wait for the owner."""

import json

from pagevoice import selftest


def test_report_lists_every_check(tmp_path, monkeypatch):
    monkeypatch.setattr(selftest, "CHECKS", {"good": lambda: "fine"})
    path = tmp_path / "report.json"
    assert selftest.write_report(path, {"extra": lambda: "also fine"})
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["passed"] and set(report["checks"]) == {"good", "extra"}
    assert report["checks"]["good"]["ok"] and report["checks"]["good"]["detail"] == "fine"


def test_a_failing_check_fails_the_build(monkeypatch):
    def broken():
        raise FileNotFoundError("_internal/language_tags/data/json/index.json")

    monkeypatch.setattr(selftest, "CHECKS", {"good": lambda: "fine", "g2p": broken})
    report = selftest.run()
    assert not report["passed"] and report["failed"] == ["g2p"]
    assert "index.json" in report["checks"]["g2p"]["detail"]


def test_the_voice_manifest_may_wait_for_the_owner(monkeypatch):
    """The real voice manifest is human-owned: until the owner publishes the voice
    release, its absence must not fail every build."""

    def missing():
        raise FileNotFoundError("voice manifest")

    monkeypatch.setattr(selftest, "CHECKS", {"manifest": missing})
    monkeypatch.delenv("PAGEVOICE_RELEASE", raising=False)
    report = selftest.run()
    assert report["passed"] and not report["checks"]["manifest"]["ok"]


def test_a_release_build_needs_the_voice_manifest(monkeypatch):
    """Review violation 1: a tagged release whose app can never get its voice must fail."""

    def missing():
        raise FileNotFoundError("voice manifest")

    monkeypatch.setattr(selftest, "CHECKS", {"manifest": missing})
    monkeypatch.setenv("PAGEVOICE_RELEASE", "1")
    report = selftest.run()
    assert not report["passed"] and report["failed"] == ["manifest"]
