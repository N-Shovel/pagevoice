"""Find and run the bundled ffmpeg (D18). Never the system's: different ffmpeg versions
mean bugs we can't reproduce, so PATH is never searched and nothing is downloaded."""

import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

EXE = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
REPO = Path(__file__).resolve().parents[3]
MISSING = (
    "PageVoice's own copy of ffmpeg is missing, so it can't make the audiobook file. "
    "Reinstall PageVoice."
)


class FfmpegError(RuntimeError):
    """ffmpeg is missing or failed. The message is plain language."""


class Cancelled(Exception):
    """The user stopped the export."""


def find_ffmpeg() -> Path:
    candidates = []
    frozen = getattr(sys, "frozen", False)
    # Development only: the installed app never runs an ffmpeg it didn't ship with (D18).
    if os.environ.get("PAGEVOICE_FFMPEG") and not frozen:
        candidates.append(Path(os.environ["PAGEVOICE_FFMPEG"]))
    if frozen:  # the installed app (M5 bundles it here)
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(base / "ffmpeg" / EXE)
    platform_dir = {"nt": "windows"}.get(os.name, "macos" if sys.platform == "darwin" else "linux")
    candidates.append(REPO / "packaging" / "ffmpeg" / "out" / platform_dir / "bin" / EXE)
    for path in candidates:
        if path.is_file():
            return path
    raise FfmpegError(MISSING)


def run(
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
    stop: threading.Event | None = None,
) -> None:
    """Run ffmpeg with args. on_progress gets 0..1; stop cancels (raises Cancelled)."""
    command = [str(find_ffmpeg()), "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    command += ["-progress", "pipe:1", *args]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
    reader.start()
    try:
        for line in process.stdout:
            if stop is not None and stop.is_set():
                raise Cancelled
            match = re.match(r"out_time_us=(\d+)", line)
            if match and duration and on_progress:
                on_progress(min(1.0, int(match.group(1)) / 1e6 / duration))
        code = process.wait()
    finally:
        # Cancelled, Ctrl+C or a failing callback: stop ffmpeg so it lets go of the
        # partial file (Windows can't delete a file another process has open).
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    reader.join(timeout=5)
    if code != 0:
        detail = "".join(errors).strip()[-500:]
        raise FfmpegError(f"Making the audio file failed. Details for a bug report: {detail}")
