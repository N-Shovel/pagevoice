"""Check that every part PageVoice needs loads: for packaged builds (M5).

PyInstaller misses data files and libraries easily (spaCy's model, misaki's dictionaries,
espeak-ng, ffmpeg, PortAudio). A build that starts can still fail on the first render,
hours into a user's evening. `pagevoice-gui --self-test REPORT` runs these checks and
writes a JSON report, so CI can test the built app itself, not the source tree.

No network, no voice model needed (it isn't bundled: it's downloaded on first run).
"""

import importlib
import json
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path


def _g2p() -> str:
    from pagevoice.voice.g2p import g2p_for

    phonemes = g2p_for("en")("The lighthouse keeper read the letter in 1945.")
    if not phonemes.strip():
        raise RuntimeError("no phonemes")
    return phonemes[:40]


def _normalize() -> str:
    from pagevoice.normalize.en import normalize

    return normalize("Dr. Smith paid $3.50 in 1945.")


def _onnxruntime() -> str:
    import onnxruntime

    return f"{onnxruntime.__version__} {onnxruntime.get_available_providers()}"


def _flac() -> str:
    import numpy as np

    from pagevoice.render.cache import RenderCache

    with tempfile.TemporaryDirectory() as tmp:
        cache = RenderCache(Path(tmp))
        cache.put("a" * 64, np.zeros(2400, dtype=np.float32), 24000)
        frames = cache.frames("a" * 64)
    if frames != 2400:
        raise RuntimeError(f"FLAC round trip gave {frames} frames")
    return "write and read"


def _ffmpeg() -> str:
    import subprocess

    from pagevoice.export.ffmpeg import find_ffmpeg

    path = find_ffmpeg()
    out = subprocess.run([str(path), "-hide_banner", "-version"], capture_output=True, text=True)
    return f"{path.name}: {out.stdout.splitlines()[0] if out.stdout else out.returncode}"


def _sound() -> str:
    import sounddevice

    return sounddevice.get_portaudio_version()[1]


def _readers() -> str:
    for name in ("pdfplumber", "pypdfium2", "pagevoice.ingest.epub", "pagevoice.ingest.pdf"):
        importlib.import_module(name)
    return "pdf and epub"


def _manifest() -> str:
    from pagevoice.voice.manifest import load_manifest

    manifest = load_manifest()  # the real one: the installed app never uses the proposed
    return f"{len(manifest.voices)} voices"


CHECKS: dict[str, Callable[[], str]] = {
    "normalize": _normalize,
    "g2p": _g2p,
    "onnxruntime": _onnxruntime,
    "flac": _flac,
    "ffmpeg": _ffmpeg,
    "sound": _sound,
    "readers": _readers,
    "manifest": _manifest,
}
# Allowed to fail before the owner publishes the voice release (model_manifest.json).
PENDING_OWNER = {"manifest"}


def run(extra: dict[str, Callable[[], str]] | None = None) -> dict:
    results = {}
    for name, check in {**CHECKS, **(extra or {})}.items():
        started = time.perf_counter()
        try:
            detail, ok = check(), True
        except BaseException as exc:  # noqa: BLE001 - every failure goes in the report
            detail, ok = "".join(traceback.format_exception_only(type(exc), exc)).strip(), False
        results[name] = {
            "ok": ok,
            "detail": detail,
            "seconds": round(time.perf_counter() - started, 2),
        }
    failed = [n for n, r in results.items() if not r["ok"] and n not in PENDING_OWNER]
    return {"passed": not failed, "failed": failed, "checks": results}


def write_report(path: Path, extra: dict[str, Callable[[], str]] | None = None) -> bool:
    report = run(extra)
    Path(path).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report["passed"]
