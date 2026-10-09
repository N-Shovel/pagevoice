---
name: roundtrip-check
description: Check rendered audio automatically by transcribing it back with faster-whisper and diffing against the expected text. Catches skipped sentences, numbers read wrong and garbled chunks. Use after changes to normalization, pronunciation, the voice pipeline or the render cache, since Claude can't listen to audio.
---

# Round-trip check

You can't hear audio, so this is how you check it: render, transcribe, diff.

## Inputs

- **Default:** `tests/voice/sentences.tsv`. The reference for each row is the `spoken` column, or `text` when `spoken` is empty or missing.
- **Optional:** one chapter of a corpus book (`--book <book-id> --chapter N`). The reference is the cleaned chapter text after normalization.

## Run

```
uv run --group roundtrip python tools/roundtrip.py
uv run --group roundtrip python tools/roundtrip.py --book <book-id> --chapter 3
```

If `tools/roundtrip.py` doesn't exist yet, build it to this contract:

1. Render each item with the engine (through the paragraph cache, so reruns are cheap).
2. Transcribe with faster-whisper (`small.en` by default, CPU, int8), in a dev-only dependency group named `roundtrip`. Add it through the `add-dependency` skill; it must never ship in the installer.
3. Normalize **both** sides the same way: lowercase, strip punctuation, unify quotes and dashes, and convert number words and digits to one form, because Whisper often writes digits.
4. Diff word by word, and report per item:
   - word error rate
   - missing words (skipped text)
   - inserted words
   - substitutions
5. Write a CSV and a short text report to `benchmarks/out/roundtrip-<date>/`.

## Reading the results

- **WER under about 5%** on a sentence is normal Whisper noise. Look at the words before blaming the voice.
- **A run of missing words** usually means text was dropped before synthesis (cleanup, chunking or the cache). Treat it as a bug.
- **A wrong number** (e.g. "nineteen forty" for "1945") is a normalizer bug. Check the `numbers`/`dates`/`money` rows.
- **Names and heteronyms** are often transcribed differently even when spoken correctly. Flag them for the owner to listen to; don't count them as failures.

## Report

- **Failures:** items with skipped text or wrong numbers, each with the reference and transcript side by side.
- **For the owner to listen to:** names, heteronyms, and anything borderline.

Always end with: a human still needs to listen for naturalness and how names come out.
