"""Kokoro synthesis on ONNX Runtime: phonemes in, 24 kHz float32 audio out."""

import logging
import re
from pathlib import Path

import numpy as np
import onnxruntime as ort

from pagevoice.voice.vocab import VOCAB

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
MAX_TOKENS = 510  # the model takes 512 ids including the two pads
STYLE_DIM = 256
# Where a long phoneme string may be split, best first.
_BREAKS = (re.compile(r"(?<=[.!?…])\s+"), re.compile(r"(?<=[,;:—])\s*"), re.compile(r"\s+"))


def providers(provider: str = "cpu") -> list[str]:
    if provider == "cpu":
        return ["CPUExecutionProvider"]
    if provider == "dml":
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    raise ValueError(f"Unknown provider {provider!r} (cpu or dml)")


def tokenize(phonemes: str) -> list[int]:
    ids = [VOCAB[c] for c in phonemes if c in VOCAB]
    dropped = {c for c in phonemes if c not in VOCAB}
    if dropped:
        # Usually misaki's unknown-word marker. Loud, because it means silent text.
        log.warning("Phonemes not in Kokoro's vocabulary, skipped: %s", "".join(sorted(dropped)))
    return ids


def _count(phonemes: str) -> int:
    return sum(c in VOCAB for c in phonemes)


def split_phonemes(phonemes: str, limit: int = MAX_TOKENS) -> list[str]:
    """Split a phoneme string into pieces of at most limit tokens, at the best breaks."""
    phonemes = phonemes.strip()
    if _count(phonemes) <= limit:
        return [phonemes] if phonemes else []
    for pattern in _BREAKS:
        parts = [p for p in pattern.split(phonemes) if p.strip()]
        if len(parts) > 1:
            break
    else:  # one unbroken run; cut it
        return [phonemes[:limit], *split_phonemes(phonemes[limit:], limit)]

    pieces: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current} {part}".strip() if current else part
        if _count(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current)
        if _count(part) > limit:
            pieces.extend(split_phonemes(part, limit))
            current = ""
        else:
            current = part
    if current:
        pieces.append(current)
    return pieces


def load_voice(path: Path) -> np.ndarray:
    """A voice file holds one 256-value style vector per input length: shape (n, 1, 256)."""
    return np.fromfile(path, dtype=np.float32).reshape(-1, 1, STYLE_DIM)


class Kokoro:
    def __init__(self, model_path: Path, *, provider: str = "cpu", threads: int = 0) -> None:
        options = ort.SessionOptions()
        if threads:
            options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=providers(provider)
        )
        active = self.session.get_providers()[0]
        if active != providers(provider)[0]:
            # ONNX Runtime silently falls back to CPU; never let that pass as DirectML.
            raise RuntimeError(f"{provider} isn't available here (running on {active})")
        self._voices: dict[Path, np.ndarray] = {}

    def voice(self, path: Path) -> np.ndarray:
        if path not in self._voices:
            self._voices[path] = load_voice(path)
        return self._voices[path]

    def synthesize(self, phonemes: str, voice_path: Path, speed: float = 1.0) -> np.ndarray:
        """Audio for a phoneme string of any length, as float32 samples at 24 kHz."""
        style_table = self.voice(voice_path)
        chunks = []
        for piece in split_phonemes(phonemes):
            ids = tokenize(piece)
            if not ids:
                continue
            style = style_table[min(len(ids), len(style_table) - 1)]
            audio = self.session.run(
                None,
                {
                    "input_ids": np.array([[0, *ids, 0]], dtype=np.int64),
                    "style": style.astype(np.float32),
                    "speed": np.array([speed], dtype=np.float32),
                },
            )[0]
            chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)
