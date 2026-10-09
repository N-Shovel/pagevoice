---
paths:
  - "src/pagevoice/voice/**"
  - "src/pagevoice/normalize/**"
  - "src/pagevoice/pronounce/**"
  - "src/pagevoice/render/**"
  - "tools/benchmark.py"
  - "tools/roundtrip.py"
---

# Voice, normalization and render rules

- **The model runs through onnxruntime only.** The CPU execution provider is the default; DirectML is an optional speed-up on Windows. Never PyTorch.
- **`voice/model_manifest.json` is human-owned.** It holds download URLs, sizes and SHA-256 checksums. A checksum mismatch is a hard error, never a warning. To propose a change, write `model_manifest.proposed.json` and ask.
- **Normalization is per language** (`normalize/en.py`). The expected spoken forms are in `tests/voice/sentences.tsv` (human-owned). Normalizer tests read that file rather than copying its answers.
- **Pronunciation:** per-book entries override global ones. Entries can be whole-word and case-sensitive ("Polish" is not "polish"). Apply them before G2P, and include them in the cache key.
- **Cache key** = hash of (normalized text, applied pronunciation entries, voice, model variant and checksum, speed, engine cache version). Anything that changes the audio must change the key.
- **Speed is measured as audio seconds ÷ wall seconds** ("× real time"), plus peak RAM. Those are the numbers the benchmark logs.
- **You can't hear audio.** Verify with the round-trip check (faster-whisper transcript diff) and say plainly that a human still needs to listen for naturalness and names.
