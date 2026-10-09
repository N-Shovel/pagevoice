---
name: benchmark
description: Measure Kokoro voice speed (× real time) and peak RAM for each model variant on the fixed sentence list, log the results to benchmarks/history.csv, compare with the previous run on the same machine, and prepare blind A/B listening pairs. Use for the week-one model decision and after any change to voice, normalization or render code.
---

# Benchmark the voice

## What gets measured

- **Input:** every row of `tests/voice/sentences.tsv`, in file order.
- **Variants:** Kokoro **fp32** and **int8**. fp16 is skipped; on CPU it saves download size, not time. Use the files pinned in `src/pagevoice/voice/model_manifest.json`.
- **Provider:** CPU by default. Add `--provider dml` for DirectML on Windows.
- **Per variant:**
  - Warm-up: one untimed sentence.
  - `audio_seconds`, `wall_seconds`, `x_realtime = audio_seconds / wall_seconds`.
  - `peak_rss_mb`: peak resident memory of the process.
  - Load time, recorded separately from synthesis.

## Run

```
uv run python tools/benchmark.py
uv run python tools/benchmark.py --variants fp32 int8 --provider cpu
```

If `tools/benchmark.py` doesn't exist yet, this is milestone M0 work. Build it to the contract above, and add any packages it needs through the `add-dependency` skill (onnxruntime, plus the G2P chosen for open question O1 in SPEC.md).

The tool reads `tests/voice/sentences.tsv` **by default**; it has no option for that path. Never put the path on the command line. The shell guard blocks commands that run `python` and name that protected file, because it can't tell a read from a write.

## Log

Append one row per variant to `benchmarks/history.csv` (committed). Columns:

```
date,git_sha,machine,os,cpu,provider,variant,threads,sentences,audio_seconds,wall_seconds,x_realtime,load_seconds,peak_rss_mb
```

- `machine`: the hostname. The owner's laptop is `laptop-tlc3d2rv`; a CI runner logs as `gha-<runner-os>`.
- Audio goes to `benchmarks/out/<date>-<variant>/` (git-ignored).
- Only compare rows from the same machine and provider. VirtualBox VM numbers are never speed numbers.

## Compare

Print the change against the previous row for the same machine, provider and variant. Flag any slowdown over 10% in `x_realtime`, or any RAM increase over 10%, and name the commits in between (`git log <old_sha>..HEAD --oneline`).

## Blind A/B listening

1. Write pairs for each sentence to `benchmarks/out/<date>-ab/`: `NN-A.wav` and `NN-B.wav`, with the fp32/int8 assignment shuffled per sentence.
2. Write the answer key to `key.json` in the same folder.
3. Tell the owner to listen, note a preference per pair, and only then open the key.

You can't judge audio quality yourself. Report the numbers, and leave the listening verdict to the owner.

## Report

- A table: variant, × real time, load time, peak RAM, and the change since the last run.
- What it means for the user. For example: "a 10-hour book takes about N hours on this laptop at int8."
