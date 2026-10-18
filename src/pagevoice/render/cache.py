"""The paragraph render cache (SPEC §8, D16, D26).

Each paragraph's audio is a FLAC file named by its cache key: a hash of everything that
changes the audio. Writes are atomic (temp file, then rename), so a crash never leaves a
half-written entry that looks valid. The cache lives in the per-user cache directory under
a size cap the user can change; the oldest entries are evicted first, never ones the
current book needs. Each book keeps an index of its keys so its cache can be cleared after
a successful export.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile
from platformdirs import user_cache_dir

log = logging.getLogger(__name__)

CACHE_VERSION = 2  # bump when rendering changes in a way the other key parts don't show
DEFAULT_CAP_BYTES = 5 * 2**30  # 5 GB
STALE_TMP_SECONDS = 3600  # older temp files are left over from a crash


def default_root() -> Path:
    override = os.environ.get("PAGEVOICE_CACHE_DIR")
    if override:
        return Path(override)
    return Path(user_cache_dir("PageVoice", appauthor=False)) / "render"


@dataclass(frozen=True)
class KeyParts:
    """Everything that changes a paragraph's audio (.claude/rules/voice.md)."""

    text: str  # normalized text, pronunciation entries applied
    entries: tuple  # the pronunciation entries that matched, as sorted tuples (no notes)
    voice: str
    variant: str
    model_sha256: str
    voice_sha256: str
    speed: float
    g2p: str  # backend and package versions
    language: str

    def key(self) -> str:
        payload = json.dumps(
            {"v": CACHE_VERSION, **self.__dict__, "speed": round(self.speed, 3)},
            sort_keys=True,
            ensure_ascii=False,
            default=list,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RenderCache:
    def __init__(self, root: Path | None = None, cap_bytes: int = DEFAULT_CAP_BYTES) -> None:
        self.root = Path(root) if root else default_root()
        self.cap_bytes = cap_bytes
        (self.root / "audio").mkdir(parents=True, exist_ok=True)
        (self.root / "books").mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        return self.root / "audio" / key[:2] / f"{key}.flac"

    def has(self, key: str) -> bool:
        return self.path(key).is_file()

    def get(self, key: str) -> np.ndarray | None:
        path = self.path(key)
        if not path.is_file():
            return None
        try:
            audio, _ = soundfile.read(str(path), dtype="float32")
        except (RuntimeError, soundfile.LibsndfileError):
            log.warning("Unreadable cache entry %s; it will be rendered again", path.name)
            path.unlink(missing_ok=True)
            return None
        os.utime(path)  # recently used: evicted last
        return audio

    def frames(self, key: str) -> int | None:
        """Length of a cached paragraph in samples, from the file header; None if absent."""
        try:
            return soundfile.info(str(self.path(key))).frames
        except (RuntimeError, soundfile.LibsndfileError):
            return None

    def put(self, key: str, audio: np.ndarray, sample_rate: int) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
        # PCM_16 wraps around past full scale, so a loud peak would become a click.
        audio = np.clip(np.asarray(audio, dtype="float32"), -1.0, 1.0)
        soundfile.write(str(tmp), audio, sample_rate, format="FLAC", subtype="PCM_16")
        os.replace(tmp, path)

    # --- per-book index and size cap ---

    def _index(self, book_id: str) -> Path:
        return self.root / "books" / f"{book_id}.json"

    def remember(self, book_id: str, keys: list[str]) -> None:
        """Add keys to the book's index. Earlier keys stay (other chapters, older edits),
        so clearing the book after export removes all of its audio."""
        index = self._index(book_id)
        tmp = index.with_name(f"{index.name}.{uuid.uuid4().hex}.tmp")
        merged = self.book_keys(book_id) | set(keys)
        tmp.write_text(json.dumps(sorted(merged)), encoding="utf-8")
        os.replace(tmp, index)

    def book_keys(self, book_id: str) -> set[str]:
        try:
            return set(json.loads(self._index(book_id).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return set()

    def clear_book(self, book_id: str) -> int:
        """Delete a book's audio that no other book uses. Returns bytes freed."""
        mine = self.book_keys(book_id)
        others: set[str] = set()
        for index in (self.root / "books").glob("*.json"):
            if index.stem != book_id:
                others |= self.book_keys(index.stem)
        freed = 0
        for key in mine - others:
            path = self.path(key)
            if path.exists():
                freed += path.stat().st_size
                path.unlink()
        self._index(book_id).unlink(missing_ok=True)
        return freed

    def clear_all(self) -> int:
        """Delete all rendered audio and every book's index. Returns bytes freed."""
        freed = 0
        for path in (self.root / "audio").rglob("*.flac"):
            freed += path.stat().st_size
            path.unlink(missing_ok=True)
        for index in (self.root / "books").glob("*.json"):
            index.unlink(missing_ok=True)
        return freed

    def size(self) -> int:
        return sum(p.stat().st_size for p in (self.root / "audio").rglob("*.flac"))

    def trim(self, protect: set[str] = frozenset()) -> int:
        """Evict least recently used entries until under the cap. Returns bytes freed.

        Also deletes temp files a crash left behind (not recent ones: another render may
        be writing them)."""
        cutoff = time.time() - STALE_TMP_SECONDS
        for tmp in self.root.rglob("*.tmp"):
            try:
                if tmp.stat().st_mtime < cutoff:
                    tmp.unlink()
            except OSError:
                pass
        files = sorted(
            (p for p in (self.root / "audio").rglob("*.flac")), key=lambda p: p.stat().st_mtime
        )
        total = sum(p.stat().st_size for p in files)
        freed = 0
        for path in files:
            if total <= self.cap_bytes:
                break
            if path.stem in protect:
                continue
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            freed += size
        return freed
