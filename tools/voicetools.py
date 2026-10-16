"""Helpers shared by the dev tools that read the fixed sentence list (benchmark, roundtrip)."""

import os
import platform
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENTENCES = ROOT / "tests" / "voice" / "sentences.tsv"
OUT = ROOT / "benchmarks" / "out"


@dataclass(frozen=True)
class Sentence:
    id: str
    category: str
    text: str
    spoken: str  # what a reader should say; same as text when the file leaves it empty


def read_sentences() -> list[Sentence]:
    rows = []
    for line in SENTENCES.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if cols[0] == "id":
            continue
        spoken = cols[3] if len(cols) > 3 and cols[3].strip() else cols[2]
        rows.append(Sentence(cols[0], cols[1], cols[2], spoken))
    return rows


def machine_name() -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return f"gha-{os.environ.get('RUNNER_OS', platform.system()).lower()}"
    return socket.gethostname().lower()


def cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def os_name() -> str:
    return f"{platform.system()} {platform.release()}"


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def peak_rss_mb() -> float:
    """Peak resident memory of this process so far, in MB."""
    if platform.system() == "Windows":
        import psutil

        return psutil.Process().memory_info().peak_wset / 2**20
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB on Linux
