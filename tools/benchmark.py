"""Benchmark Kokoro: speed (x real time) and peak RAM per model variant.

    uv run python tools/benchmark.py
    uv run python tools/benchmark.py --variants fp32 int8 --provider cpu

Reads the fixed sentence list (tests/voice/sentences.tsv) by default; there is no option
for that path. Each variant runs in its own process so peak RAM is measured separately.
Appends one row per variant to benchmarks/history.csv, compares with the previous row for
the same machine, provider and variant, and writes blind A/B pairs when two variants ran.
See .claude/skills/benchmark/SKILL.md.
"""

import argparse
import csv
import json
import random
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voicetools import (  # noqa: E402
    OUT,
    ROOT,
    cpu_name,
    git_sha,
    machine_name,
    os_name,
    peak_rss_mb,
    read_sentences,
)

HISTORY = ROOT / "benchmarks" / "history.csv"
COLUMNS = [
    "date",
    "git_sha",
    "machine",
    "os",
    "cpu",
    "provider",
    "variant",
    "threads",
    "sentences",
    "audio_seconds",
    "wall_seconds",
    "x_realtime",
    "load_seconds",
    "peak_rss_mb",
]
SLOWDOWN = 0.10


def worker(args: argparse.Namespace) -> int:
    """Run one variant and print its numbers as JSON on the last line."""
    from pagevoice.audio import write_wav
    from pagevoice.voice.download import ensure_file
    from pagevoice.voice.g2p import g2p_for
    from pagevoice.voice.kokoro import SAMPLE_RATE, Kokoro
    from pagevoice.voice.manifest import load_manifest

    manifest = load_manifest(allow_proposed=True)
    use_source = args.from_source or manifest.is_proposed
    model_path = ensure_file(manifest.model_entry(args.worker), use_source=use_source)
    voice_path = ensure_file(manifest.voice_entry(args.voice), use_source=use_source)

    sentences = read_sentences()
    g2p = g2p_for("en", args.g2p)
    t0 = time.perf_counter()
    phonemes = [g2p(s.text) for s in sentences]
    g2p_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    voice = Kokoro(model_path, provider=args.provider, threads=args.threads)
    load_seconds = time.perf_counter() - t0

    voice.synthesize(phonemes[0], voice_path)  # warm-up, untimed

    out_dir = Path(args.out)
    audio_seconds = wall_seconds = 0.0
    for index, (sentence, ph) in enumerate(zip(sentences, phonemes, strict=True), 1):
        t0 = time.perf_counter()
        audio = voice.synthesize(ph, voice_path)
        wall_seconds += time.perf_counter() - t0
        audio_seconds += len(audio) / SAMPLE_RATE
        write_wav(out_dir / f"{index:02d}-{sentence.id}.wav", audio, SAMPLE_RATE)

    result = {
        "sentences": len(sentences),
        "audio_seconds": round(audio_seconds, 3),
        "wall_seconds": round(wall_seconds, 3),
        "x_realtime": round(audio_seconds / wall_seconds, 3),
        "load_seconds": round(load_seconds, 3),
        "g2p_seconds": round(g2p_seconds, 3),
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "manifest": manifest.path.name,
    }
    print(json.dumps(result))
    return 0


def run_variant(variant: str, args: argparse.Namespace, out_dir: Path) -> dict:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        variant,
        "--provider",
        args.provider,
        "--threads",
        str(args.threads),
        "--voice",
        args.voice,
        "--g2p",
        args.g2p,
        "--out",
        str(out_dir),
    ]
    if args.from_source:
        command.append("--from-source")
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        sys.stderr.write(done.stderr)
        raise SystemExit(f"Benchmark worker for {variant} failed")
    return json.loads(done.stdout.strip().splitlines()[-1])


def previous_row(row: dict) -> dict | None:
    """Last logged row for the same machine, CPU, provider and variant.

    The CPU is part of the match because CI runners under one machine name vary.
    """
    if not HISTORY.exists():
        return None
    match = ("machine", "cpu", "provider", "variant")
    with HISTORY.open(encoding="utf-8", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if all(r[k] == str(row[k]) for k in match)]
    return rows[-1] if rows else None


def append_row(row: dict) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    new = not HISTORY.exists()
    with HISTORY.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        if new:
            writer.writeheader()
        writer.writerow({k: row[k] for k in COLUMNS})


def compare(row: dict, before: dict | None) -> str:
    if before is None:
        return "first run on this machine"
    speed = row["x_realtime"] / float(before["x_realtime"]) - 1
    ram = row["peak_rss_mb"] / float(before["peak_rss_mb"]) - 1
    text = f"x_realtime {speed:+.0%}, RAM {ram:+.0%} vs {before['git_sha']}"
    if speed < -SLOWDOWN or ram > SLOWDOWN:
        log = subprocess.run(
            ["git", "log", f"{before['git_sha']}..HEAD", "--oneline"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        text += f"  << REGRESSION. Commits since:\n{log or '(none)'}"
    return text


def write_ab(dirs: dict[str, Path], ab_dir: Path) -> None:
    """Blind pairs: NN-A.wav / NN-B.wav, variant order shuffled per sentence."""
    first, second = list(dirs)
    ab_dir.mkdir(parents=True, exist_ok=True)
    rng = random.SystemRandom()
    key = {}
    for wav in sorted(dirs[first].glob("*.wav")):
        number = wav.name.split("-", 1)[0]
        order = [first, second]
        rng.shuffle(order)
        for label, variant in zip("AB", order, strict=True):
            shutil.copyfile(dirs[variant] / wav.name, ab_dir / f"{number}-{label}.wav")
        key[number] = {"sentence": wav.stem.split("-", 1)[1], "A": order[0], "B": order[1]}
    (ab_dir / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    (ab_dir / "README.txt").write_text(
        "Listen to each NN-A.wav / NN-B.wav pair and note which you prefer (or 'same').\n"
        "Only then open key.json to see which variant was which.\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--variants", nargs="+", default=["fp32", "int8"])
    parser.add_argument("--provider", choices=["cpu", "dml"], default="cpu")
    parser.add_argument("--threads", type=int, default=0, help="0 = ONNX Runtime default")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--g2p", default="misaki")
    parser.add_argument("--from-source", action="store_true", help="download from source URLs")
    parser.add_argument("--no-log", action="store_true", help="don't append to history.csv")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--out", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.worker:
        return worker(args)

    today = date.today().isoformat()
    machine, sha = machine_name(), git_sha()
    dirs: dict[str, Path] = {}
    report = []
    for variant in args.variants:
        out_dir = OUT / f"{today}-{variant}"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        print(f"Running {variant} on {args.provider}...", flush=True)
        result = run_variant(variant, args, out_dir)
        dirs[variant] = out_dir
        row = {
            "date": today,
            "git_sha": sha,
            "machine": machine,
            "os": os_name(),
            "cpu": cpu_name(),
            "provider": args.provider,
            "variant": variant,
            "threads": args.threads or "default",
            **result,
        }
        change = compare(row, previous_row(row))
        if not args.no_log:
            append_row(row)
        report.append((row, change))

    print(f"\nMachine {machine} ({cpu_name()}), provider {args.provider}, voice {args.voice}")
    print(f"{'variant':8} {'x real time':>12} {'load s':>8} {'peak RAM MB':>12}  change")
    for row, change in report:
        print(
            f"{row['variant']:8} {row['x_realtime']:>12.2f} {row['load_seconds']:>8.2f} "
            f"{row['peak_rss_mb']:>12.0f}  {change}"
        )
    for row, _ in report:
        # End to end includes G2P (spaCy tagging), which x_realtime leaves out.
        end_to_end = row["audio_seconds"] / (row["wall_seconds"] + row["g2p_seconds"])
        hours = 10 / end_to_end
        print(
            f"{row['variant']}: {end_to_end:.2f}x real time including G2P; a 10-hour book "
            f"takes about {hours:.1f} hours on this machine."
        )

    if len(dirs) == 2:
        ab_dir = OUT / f"{today}-ab"
        if ab_dir.exists():
            shutil.rmtree(ab_dir)
        write_ab(dirs, ab_dir)
        print(f"\nBlind A/B pairs: {ab_dir} (listen first, then open key.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
