"""Round-trip check: render, transcribe back with faster-whisper, diff against the text.

    uv run --group roundtrip python tools/roundtrip.py
    uv run --group roundtrip python tools/roundtrip.py --g2p espeak --label espeak

Reads the fixed sentence list (tests/voice/sentences.tsv) by default; there is no option
for that path. The reference for each row is its spoken form. Writes report.csv and
report.txt to benchmarks/out/roundtrip-<date>[-label]/. See
.claude/skills/roundtrip-check/SKILL.md. A human still needs to listen for naturalness and
names; this only catches skipped, garbled and misread words.
"""

import argparse
import csv
import difflib
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from voicetools import OUT, Sentence, read_sentences  # noqa: E402

LISTEN_CATEGORIES = {"names", "heteronyms"}
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": " ", "–": " ", "-": " "})
_NUMBER = re.compile(r"^(\d+)(st|nd|rd|th|s)?$")


def _number_words(token: str) -> str:
    from num2words import num2words

    match = _NUMBER.match(token)
    if not match:
        return token
    value, suffix = int(match.group(1)), match.group(2)
    if suffix in ("st", "nd", "rd", "th"):
        return num2words(value, to="ordinal")
    if 1100 <= value <= 2099 and len(match.group(1)) == 4:
        words = num2words(value, to="year")
    else:
        words = num2words(value)
    if suffix == "s":
        words = words[:-1] + "ies" if words.endswith("y") else words + "s"
    return words


def words(text: str) -> list[str]:
    """Lowercase, unify quotes and dashes, drop punctuation, spell out digits."""
    text = text.translate(_QUOTES).lower()
    text = text.replace("$", " dollars ").replace("%", " percent ").replace("&", " and ")
    text = re.sub(r"(\d),(\d{3})", r"\1\2", text)
    text = re.sub(r"[^\w\s']", " ", text)
    out: list[str] = []
    for token in text.split():
        token = token.strip("'")
        if not token:
            continue
        spelled = _number_words(token).replace("-", " ").replace(",", " ")
        out.extend(spelled.split())
    return out


@dataclass
class Diff:
    wer: float
    missing: list[str]
    inserted: list[str]
    substituted: list[tuple[str, str]]


def diff(reference: list[str], hypothesis: list[str]) -> Diff:
    missing, inserted, substituted = [], [], []
    matcher = difflib.SequenceMatcher(a=reference, b=hypothesis, autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "delete":
            missing += reference[a0:a1]
        elif op == "insert":
            inserted += hypothesis[b0:b1]
        elif op == "replace":
            ref, hyp = reference[a0:a1], hypothesis[b0:b1]
            substituted += list(zip(ref, hyp, strict=False))
            if len(ref) > len(hyp):
                missing += ref[len(hyp) :]
            elif len(hyp) > len(ref):
                inserted += hyp[len(ref) :]
    errors = len(missing) + len(inserted) + len(substituted)
    return Diff(errors / max(len(reference), 1), missing, inserted, substituted)


def to_16k(path: Path):
    """Whisper wants 16 kHz mono float32; resample in memory (no PyAV)."""
    import numpy as np

    from pagevoice.audio import read_wav

    samples, rate = read_wav(path)
    count = int(len(samples) * 16000 / rate)
    return np.interp(
        np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples
    ).astype(np.float32)


def render(sentences: list[Sentence], args: argparse.Namespace, out_dir: Path) -> list[Path]:
    """Render through the engine: normalizer, pronunciation lists and the paragraph cache,
    so reruns are cheap and the check sees exactly what a book would get."""
    from pagevoice.audio import write_wav
    from pagevoice.document import Book, Chapter, Paragraph
    from pagevoice.pronounce.store import entries_for
    from pagevoice.render.cache import RenderCache
    from pagevoice.render.renderer import Renderer
    from pagevoice.voice.engine import VoiceSetup
    from pagevoice.voice.kokoro import SAMPLE_RATE
    from pagevoice.voice.manifest import load_manifest

    manifest = load_manifest(allow_proposed=True)
    voice = VoiceSetup(manifest, variant=args.variant, voice=args.voice, g2p_backend=args.g2p)
    if not voice.ready():
        voice.download(use_source=manifest.is_proposed)
    book = Book(
        title="sentences",
        chapters=[Chapter("sentences", [Paragraph.plain(s.text) for s in sentences])],
    )
    renderer = Renderer(book, voice, RenderCache(), book_id="roundtrip-sentences",
                        pronunciations=entries_for())  # fmt: skip
    renderer.run()
    paths = []
    for index, (sentence, item) in enumerate(zip(sentences, renderer.items, strict=True), 1):
        path = out_dir / "audio" / f"{index:02d}-{sentence.id}.wav"
        write_wav(path, renderer.cache.get(item.key), SAMPLE_RATE)
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--g2p", default="misaki")
    parser.add_argument("--variant", default="fp32")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--whisper", default="small.en")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    from faster_whisper import WhisperModel

    sentences = read_sentences()
    name = f"roundtrip-{date.today().isoformat()}" + (f"-{args.label}" if args.label else "")
    out_dir = OUT / name
    print(f"Rendering {len(sentences)} sentences ({args.variant}, {args.g2p})...", flush=True)
    paths = render(sentences, args, out_dir)

    print(f"Transcribing with faster-whisper {args.whisper}...", flush=True)
    whisper = WhisperModel(args.whisper, device="cpu", compute_type="int8")
    rows = []
    for sentence, path in zip(sentences, paths, strict=True):
        segments, _ = whisper.transcribe(to_16k(path), language="en", beam_size=5)
        transcript = " ".join(s.text.strip() for s in segments)
        # Whisper often writes the printed form ("Mr.", "IV") for a correct reading, so
        # score against both the spoken and the printed reference and keep the better one.
        heard = words(transcript)
        result = min(
            diff(words(sentence.spoken), heard),
            diff(words(sentence.text), heard),
            key=lambda d: d.wer,
        )
        rows.append((sentence, transcript, result))

    with (out_dir / "report.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["id", "category", "wer", "missing", "inserted", "subs", "ref", "heard"])
        for s, heard, d in rows:
            subs = "; ".join(f"{a}->{b}" for a, b in d.substituted)
            writer.writerow(
                [s.id, s.category, f"{d.wer:.3f}", " ".join(d.missing), " ".join(d.inserted)]
                + [subs, s.spoken, heard]
            )

    total_ref = sum(len(words(s.spoken)) for s, _, _ in rows)
    total_err = sum(d.wer * len(words(s.spoken)) for s, _, d in rows)
    lines = [
        f"Round-trip {name}: g2p={args.g2p} variant={args.variant} voice={args.voice}",
        f"Overall WER {total_err / total_ref:.1%} over {len(rows)} sentences.",
        "",
        "Failures (skipped text or misread words, WER over 5%):",
    ]
    for s, heard, d in rows:
        if s.category in LISTEN_CATEGORIES or d.wer <= 0.05:
            continue
        lines += [f"  {s.id} WER {d.wer:.0%}", f"    ref:   {s.spoken}", f"    heard: {heard}"]
    lines += ["", "For the owner to listen to (names and heteronyms):"]
    for s, heard, d in rows:
        if s.category in LISTEN_CATEGORIES:
            lines.append(f"  {s.id} WER {d.wer:.0%}  heard: {heard}")
    lines += ["", "A human still needs to listen for naturalness and how names come out."]
    report = "\n".join(lines)
    (out_dir / "report.txt").write_text(report + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
