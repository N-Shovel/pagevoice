---
paths:
  - "tests/**"
---

# Test rules

- **Golden answers are human-owned:** `tests/corpus/**/expected/` and `tests/voice/sentences.tsv`. A hook blocks edits to them. When a golden test fails, fix the code. If you believe the expectation is wrong, write your version to the book's `candidate/` folder (or `sentences.proposed.tsv`), explain why, and ask the owner.
- **No update-the-snapshot flags.** No test or tool may write to `expected/`.
- **Copyrighted books** go in `tests/corpus/private/` (git-ignored), never `public/`. Tests that need them skip cleanly when the folder is missing, so CI and fresh clones still pass.
- **Unit tests never touch the network.** Tests that need the voice model are marked `@pytest.mark.slow` and skip cleanly if the model isn't downloaded.
- **Prefer real books over invented strings** for cleanup tests. A synthetic snippet is fine for a unit test of one function, but the golden corpus is the real check.
