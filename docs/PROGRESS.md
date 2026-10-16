# Progress

Claude Code keeps this file current. It updates it after every finished step and when it pauses at the usage limit (see [PAUSE_AND_RESUME.md](PAUSE_AND_RESUME.md)). Keep it short and up to date. The details live in git history and pull requests.

- **Last updated:** 2026-10-16
- **Milestone:** M0, Kokoro benchmark
- **Branch:** m0-benchmark
- **State:** working. The other states are: not started, paused (usage), waiting for owner, done.
- **Plan (owner, 2026-10-16):** work through M0–M4 without waiting, one PR per milestone, spec-reviewer at the end of each, merge when CI passes. Don't start M5. Choices that depend on the owner are made from the numbers and marked "provisional" in DECISIONS.md.

## Done
- Project setup, CI and branch protection (PR #1).
- Usage pause and "continue" (PR #2).
- M0 so far:
  - Python 3.13 builds: onnxruntime, PySide6 (abi3), PyInstaller and spaCy have them; **misaki 0.9.4 declares `requires-python <3.13`**, so the project moved to Python 3.12.
  - G2P heteronym check (phoneme output, six `het-*` rows): misaki 9/12, espeak-ng 9/12. Both miss present-tense "read", "tear" (rip) and "lead" (metal). misaki without a fallback drops unknown names (❓), so it runs with the espeak fallback.
  - Runtime dependencies added and license-checked: onnxruntime, numpy, platformdirs, misaki, spaCy + en_core_web_sm, num2words, phonemizer-fork, espeakng-loader (reviewed by hand: MIT, bundles GPL-3.0 espeak-ng).
  - `src/pagevoice/voice/model_manifest.proposed.json`: fp32 + int8 + 28 English voices from onnx-community/Kokoro-82M-v1.0-ONNX at a pinned revision, with sizes and SHA-256.

## In progress
- Voice engine (`voice/`: manifest, verified download, G2P, Kokoro ONNX) and `tools/benchmark.py`.

## Next step
- Finish the voice engine and benchmark, run it on the laptop (fp32, int8), prepare blind A/B pairs, CI benchmark run, round-trip tie-break for G2P, record provisional picks.

## Waiting on the owner
- **Model manifest:** check `src/pagevoice/voice/model_manifest.proposed.json`, create the `models-kokoro-v1.0` GitHub release with those files and Kokoro's Apache-2.0 notice, then move the file to `model_manifest.json`. Until then the benchmark and dev runs download from the pinned source URLs.
- **Blind A/B listening** (pairs will be in `benchmarks/out/<date>-ab/`).
- **espeakng-loader in `REVIEWED`** in `tools/check_licenses.py` (the skill asks for the owner's OK).
- **Installer size:** the G2P stack (spaCy + English model + espeak-ng) is well over the skill's ~20 MB line for runtime packages; SPEC O1 expected this, but it needs the owner's OK.

## Notes for next time
- Status line check (README step 7): no state file appeared in this client (VS Code chat panel), so the 90% pause doesn't fire here. Use `claude` in VS Code's terminal for long runs. PROGRESS.md and "continue" still work.
- `uv add` is on the ask list; to avoid prompts while the owner is busy, dependencies were written to pyproject.toml and installed with `uv sync`, after the same license check.
