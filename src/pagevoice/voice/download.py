"""First-run model download: the only network access in PageVoice.

Every file is checked against the SHA-256 in the manifest. A mismatch is a hard error:
the bad file is deleted and never used.
"""

import hashlib
import logging
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

from platformdirs import user_data_dir

from pagevoice.voice.manifest import FileEntry

log = logging.getLogger(__name__)

CHUNK = 1 << 20
Progress = Callable[[int, int], None]  # (bytes done, bytes total)


class ChecksumError(RuntimeError):
    """A downloaded or cached file doesn't match the manifest."""


def models_dir() -> Path:
    override = os.environ.get("PAGEVOICE_MODELS_DIR")
    if override:
        return Path(override)
    return Path(user_data_dir("PageVoice", appauthor=False)) / "models"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def is_valid(path: Path, entry: FileEntry) -> bool:
    return path.is_file() and path.stat().st_size == entry.size and sha256_of(path) == entry.sha256


def ensure_file(
    entry: FileEntry,
    folder: Path | None = None,
    *,
    use_source: bool = False,
    progress: Progress | None = None,
) -> Path:
    """Return the verified local copy of entry, downloading it first if needed.

    use_source downloads from the pinned upstream URL instead of our release; the
    checksum is the same either way. Dev tools only (benchmark, round-trip) while the
    manifest is still the proposed one; the app always uses our release (D9).
    """
    if getattr(sys, "frozen", False):
        use_source = False  # the installed app downloads from our release only (D9)
    folder = folder or models_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / entry.name
    if target.is_file() and target.stat().st_size == entry.size:
        if sha256_of(target) == entry.sha256:
            return target
        log.warning("Cached %s fails its checksum; downloading again", target)
        target.unlink()

    url = entry.source_url if use_source else entry.url
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    done = 0
    log.info("Downloading %s from %s", entry.name, url)
    request = urllib.request.Request(url, headers={"User-Agent": "PageVoice"})
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
        while block := response.read(CHUNK):
            out.write(block)
            digest.update(block)
            done += len(block)
            if progress:
                progress(done, entry.size)
    if done != entry.size or digest.hexdigest() != entry.sha256:
        part.unlink(missing_ok=True)
        raise ChecksumError(
            f"{entry.name} from {url} doesn't match the manifest "
            f"(got {done} bytes, sha256 {digest.hexdigest()}). It was deleted and not used."
        )
    os.replace(part, target)
    return target
