"""Check that every part PageVoice needs loads: for packaged builds (M5).

PyInstaller misses data files and libraries easily (spaCy's model, misaki's dictionaries,
espeak-ng, ffmpeg, PortAudio). A build that starts can still fail on the first render,
hours into a user's evening. `pagevoice-gui --self-test REPORT` runs these checks and
writes a JSON report, so CI can test the built app itself, not the source tree.

No network, no voice model needed (it isn't bundled: it's downloaded on first run).
"""

import importlib
import json
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path


def _g2p() -> str:
    """Dictionary words go through misaki and spaCy; names it doesn't know (Siobhan,
    Nguyen) go to espeak-ng. Both must work: a build without espeak-ng's data would leave
    every unknown name silent."""
    from pagevoice.voice.g2p import g2p_for

    g2p = g2p_for("en")
    results = []
    for what, text in (
        ("dictionary words", "The lighthouse keeper read the letter in nineteen forty-five."),
        ("unknown names", "Siobhan Nguyen met Xiomara."),
    ):
        phonemes = g2p(text)
        # last_warning describes this call only: check it before the next one.
        if not phonemes.strip() or g2p.last_warning:
            raise RuntimeError(f"G2P failed on {what}: {phonemes!r} {g2p.last_warning}")
        results.append(phonemes[:20])
    return " / ".join(f"{r}…" for r in results)


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
    """Encode a moment of silence the way export does: AAC in an M4B (ipod muxer) and
    MP3 (LAME), with the bundled binary. Its version line alone proves too little."""
    import numpy as np
    import soundfile

    from pagevoice.export.ffmpeg import find_ffmpeg, run

    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "in.flac"
        soundfile.write(str(source), np.zeros(2400, dtype=np.float32), 24000, format="FLAC")
        for out, codec, muxer in (("a.m4b", "aac", "ipod"), ("a.mp3", "libmp3lame", "mp3")):
            target = Path(tmp) / out
            run(["-i", str(source), "-c:a", codec, "-b:a", "64k", "-f", muxer, str(target)])
            if not target.is_file() or target.stat().st_size < 100:
                raise RuntimeError(f"ffmpeg wrote no {out}")
    return f"{find_ffmpeg().name}: M4B and MP3 encoded"


def _sound() -> str:
    from pagevoice.render.playback import bundled_portaudio, import_sounddevice

    version = import_sounddevice().get_portaudio_version()[1]
    bundled = bundled_portaudio()
    return f"{version} ({'bundled ' + bundled.name if bundled else 'from the package'})"


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
# Allowed to fail before the owner publishes the voice release, except in a release
# build (PAGEVOICE_RELEASE=1, set for version tags): an installer whose first-run download
# can't work must never be published.
PENDING_OWNER = {"manifest"}


def _waived() -> set[str]:
    return set() if os.environ.get("PAGEVOICE_RELEASE") == "1" else PENDING_OWNER


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
    failed = [n for n, r in results.items() if not r["ok"] and n not in _waived()]
    return {"passed": not failed, "failed": failed, "checks": results}


def write_report(path: Path, extra: dict[str, Callable[[], str]] | None = None) -> bool:
    report = run(extra)
    Path(path).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report["passed"]
