"""Small audio helpers shared by the engine and dev tools."""

import os
import wave
from pathlib import Path

import numpy as np


def to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write mono 16-bit PCM atomically (temp file, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(to_pcm16(samples))
    os.replace(tmp, path)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as src:
        rate = src.getframerate()
        frames = src.readframes(src.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0, rate
