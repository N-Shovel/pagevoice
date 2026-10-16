"""Voice: manifest, checksum-verified download, phoneme splitting, and (slow) synthesis."""

import hashlib

import pytest

from pagevoice.voice import download
from pagevoice.voice.download import ChecksumError, ensure_file
from pagevoice.voice.kokoro import MAX_TOKENS, split_phonemes, tokenize
from pagevoice.voice.manifest import PROPOSED, FileEntry, ManifestError, load_manifest


def entry_for(path, data: bytes, *, sha: str | None = None) -> FileEntry:
    return FileEntry(
        name="model.onnx",
        url=path.as_uri(),
        source_url=path.as_uri(),
        size=len(data),
        sha256=sha or hashlib.sha256(data).hexdigest(),
    )


def test_proposed_manifest_is_well_formed():
    manifest = load_manifest(PROPOSED)
    assert manifest.is_proposed
    assert set(manifest.models) == {"fp32", "int8"}
    assert "af_heart" in manifest.voices
    for entry in [*manifest.models.values(), *manifest.voices.values()]:
        assert entry.url.startswith("https://github.com/N-Shovel/pagevoice/releases/download/")
        assert entry.size > 0


def test_unknown_variant_is_a_clear_error():
    with pytest.raises(ManifestError, match="fp16"):
        load_manifest(PROPOSED).model_entry("fp16")


def test_download_verifies_checksum(tmp_path):
    source = tmp_path / "src.bin"
    source.write_bytes(b"kokoro" * 100)
    entry = entry_for(source, source.read_bytes())
    target = ensure_file(entry, tmp_path / "models")
    assert target.read_bytes() == source.read_bytes()
    assert ensure_file(entry, tmp_path / "models") == target  # cached copy reused


def test_checksum_mismatch_is_a_hard_error(tmp_path):
    source = tmp_path / "src.bin"
    source.write_bytes(b"tampered")
    entry = entry_for(source, b"tampered", sha="0" * 64)
    with pytest.raises(ChecksumError):
        ensure_file(entry, tmp_path / "models")
    assert not list((tmp_path / "models").iterdir())  # nothing half-written left behind


def test_corrupt_cached_file_is_replaced(tmp_path):
    data = b"good model bytes"
    source = tmp_path / "src.bin"
    source.write_bytes(data)
    entry = entry_for(source, data)
    folder = tmp_path / "models"
    folder.mkdir()
    (folder / entry.name).write_bytes(b"x" * len(data))
    assert ensure_file(entry, folder).read_bytes() == data


def test_models_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PAGEVOICE_MODELS_DIR", str(tmp_path))
    assert download.models_dir() == tmp_path


def test_long_phonemes_split_under_the_token_limit():
    sentence = "ðə kˈæt sˈæt ˈɔn ðə mˈæt, ənd ðə dˈɔɡ slˈɛpt. "
    long = sentence * 40
    pieces = split_phonemes(long)
    assert len(pieces) > 1
    assert all(len(tokenize(p)) <= MAX_TOKENS for p in pieces)
    # nothing is lost: the pieces hold every phoneme of the input
    assert "".join(long.split()) == "".join("".join(pieces).split())


def test_unbroken_run_is_still_split():
    pieces = split_phonemes("a" * (MAX_TOKENS * 2 + 5))
    assert all(len(tokenize(p)) <= MAX_TOKENS for p in pieces)
    assert sum(len(p) for p in pieces) == MAX_TOKENS * 2 + 5


@pytest.mark.slow
def test_synthesis_produces_audio():
    from pagevoice.voice.g2p import g2p_for
    from pagevoice.voice.kokoro import SAMPLE_RATE, Kokoro

    manifest = load_manifest(allow_proposed=True)
    folder = download.models_dir()
    model = folder / manifest.model_entry("int8").name
    voice = folder / manifest.voice_entry("af_heart").name
    if not (model.exists() and voice.exists()):
        pytest.skip("voice model not downloaded")
    audio = Kokoro(model).synthesize(g2p_for("en")("Hello there."), voice)
    assert 0.3 < len(audio) / SAMPLE_RATE < 5
    assert float(abs(audio).max()) > 0.01


def test_out_of_vocabulary_phonemes_are_reported(caplog):
    assert tokenize("hˈɛlO ❓") == tokenize("hˈɛlO ")
    assert "❓" in caplog.text


def test_language_codes_are_normalized():
    from pagevoice.voice.g2p import normalize_language

    assert normalize_language(" en_GB ") == "en-gb"


def test_non_english_is_refused():
    from pagevoice.voice.g2p import g2p_for

    with pytest.raises(ValueError, match="English only"):
        g2p_for("fr")


def test_g2p_never_downloads_the_spacy_model(monkeypatch):
    """misaki would pip-download a 'missing' spaCy model; PageVoice must refuse instead."""
    import spacy.util

    from pagevoice.voice import g2p_en

    g2p_en._load.cache_clear()
    monkeypatch.setattr(spacy.util, "is_package", lambda name: False)
    try:
        with pytest.raises(g2p_en.G2PError):
            g2p_en._load("misaki", False)
    finally:
        g2p_en._load.cache_clear()
