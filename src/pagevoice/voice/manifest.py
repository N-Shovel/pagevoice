"""The model manifest: pinned download URLs, sizes and SHA-256 checksums.

`model_manifest.json` is human-owned. Until the owner moves it in, development tools
(the benchmark) may opt in to `model_manifest.proposed.json`; the app itself never does.
"""

import json
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "model_manifest.json"
PROPOSED = HERE / "model_manifest.proposed.json"


class ManifestError(RuntimeError):
    """The manifest is missing or malformed."""


@dataclass(frozen=True)
class FileEntry:
    name: str
    url: str
    source_url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    path: Path
    model: str
    sample_rate: int
    max_tokens: int
    style_dim: int
    models: dict[str, FileEntry]
    voices: dict[str, FileEntry]

    @property
    def is_proposed(self) -> bool:
        return self.path.name != MANIFEST.name

    def model_entry(self, variant: str) -> FileEntry:
        try:
            return self.models[variant]
        except KeyError:
            raise ManifestError(
                f"Unknown model variant {variant!r}. Known: {', '.join(self.models)}"
            ) from None

    def voice_entry(self, voice: str) -> FileEntry:
        try:
            return self.voices[voice]
        except KeyError:
            raise ManifestError(f"Unknown voice {voice!r}.") from None


def _entry(raw: dict) -> FileEntry:
    sha = str(raw["sha256"]).lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ManifestError(f"Bad SHA-256 for {raw.get('name')!r}")
    return FileEntry(
        name=str(raw["name"]),
        url=str(raw["url"]),
        source_url=str(raw.get("source_url") or raw["url"]),
        size=int(raw["size"]),
        sha256=sha,
    )


def load_manifest(path: Path | None = None, *, allow_proposed: bool = False) -> Manifest:
    """Read the manifest. With allow_proposed, fall back to the proposed one if needed."""
    if path is None:
        path = MANIFEST
        if not path.exists() and allow_proposed:
            path = PROPOSED
    if not path.exists():
        raise ManifestError(f"Model manifest not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Manifest(
            path=path,
            model=str(raw["model"]),
            sample_rate=int(raw["sample_rate"]),
            max_tokens=int(raw["max_tokens"]),
            style_dim=int(raw["style_dim"]),
            models={k: _entry(v) for k, v in raw["models"].items()},
            voices={k: _entry(v) for k, v in raw["voices"].items()},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManifestError(f"Malformed model manifest {path}: {exc}") from exc
