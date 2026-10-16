"""Small command line for driving the engine during development and testing.

pagevoice info BOOK                      chapters, flags and removals
pagevoice download                       first-run model download (checksum-verified)
pagevoice render BOOK --out DIR          render to the cache, write chapter audio
"""

import argparse
import hashlib
import sys
import threading
from collections import Counter
from pathlib import Path

from pagevoice import __version__


def _manifest(args):
    from pagevoice.voice.manifest import load_manifest

    return load_manifest(allow_proposed=args.dev_proposed_manifest)


def _voice(args):
    from pagevoice.voice.engine import VoiceSetup

    return VoiceSetup(
        _manifest(args), variant=args.variant, voice=args.voice, provider=args.provider
    )


def cmd_info(args) -> int:
    from pagevoice.ingest import read_book

    book = read_book(Path(args.book), language=args.language)
    print(f"{book.title} by {book.author or 'unknown'} [{book.language}, {book.source_format}]")
    for flag in book.flags:
        print(f"  page {flag.page}: {flag.kind}: {flag.message}")
    for number, chapter in enumerate(book.chapters, 1):
        readable = chapter.readable()
        words = sum(len(t.split()) for t in readable)
        print(f"{number:3}. {chapter.title[:60]:60} {words:7} words, {len(chapter.notes)} notes")
    reasons = Counter(s.reason.value for s in book.removals)
    print("Removed (restorable):", ", ".join(f"{k} {v}" for k, v in reasons.most_common()))
    return 0


def cmd_download(args) -> int:
    voice = _voice(args)

    def progress(done: int, total: int) -> None:
        print(f"\r  {done / 2**20:7.1f} / {total / 2**20:.1f} MB", end="", flush=True)

    voice.download(progress, use_source=voice.manifest.is_proposed)
    print("\nVoice files ready.")
    return 0


def cmd_render(args) -> int:
    from pagevoice.audio import write_wav
    from pagevoice.ingest import read_book
    from pagevoice.pronounce.store import entries_for
    from pagevoice.render.cache import RenderCache
    from pagevoice.render.renderer import Renderer, RenderSettings
    from pagevoice.voice.engine import VoiceNotReady
    from pagevoice.voice.kokoro import SAMPLE_RATE

    path = Path(args.book)
    book = read_book(path, language=args.language)
    if args.chapters:
        first, _, last = args.chapters.partition("-")
        book.chapters = book.chapters[int(first) - 1 : int(last or first)]
    book_id = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    renderer = Renderer(
        book,
        _voice(args),
        RenderCache(),
        book_id=book_id,
        settings=RenderSettings(speed=args.speed),
        pronunciations=entries_for(Path(args.pronunciations) if args.pronunciations else None),
    )

    def progress(p) -> None:
        eta = f"{p.eta_seconds / 60:.0f} min left" if p.eta_seconds else ""
        print(f"\r  {p.done}/{p.total} paragraphs  {eta:20}", end="", flush=True)

    stop = threading.Event()
    try:
        result = renderer.run(progress, stop=stop)
    except VoiceNotReady:
        print("The voice isn't downloaded yet. Run: pagevoice download", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        stop.set()
        print("\nStopped. Run the same command again to carry on where it left off.")
        return 130
    print(f"\nRendered {result.rendered}, from cache {result.cached}, failed {len(result.failed)}.")
    out = Path(args.out)
    for index, chapter in enumerate(book.chapters):
        target = out / f"{index + 1:03d}.wav"
        write_wav(target, renderer.chapter_audio(index), SAMPLE_RATE)
        print(f"  {target}  {chapter.title[:60]}")
    return 1 if result.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pagevoice", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=f"pagevoice {__version__}")
    sub = parser.add_subparsers(dest="command")

    def voice_options(p):
        p.add_argument("--voice", default="af_heart")
        p.add_argument("--variant", default="fp32", choices=["fp32", "int8"])
        p.add_argument("--provider", default="cpu", choices=["cpu", "dml"])
        p.add_argument(
            "--dev-proposed-manifest",
            action="store_true",
            help="development only: use model_manifest.proposed.json until the real one exists",
        )

    info = sub.add_parser("info", help="show chapters, flags and removals")
    info.add_argument("book")
    info.add_argument("--language")
    download = sub.add_parser("download", help="download the voice (first run)")
    voice_options(download)
    render = sub.add_parser("render", help="render a book to chapter audio files")
    render.add_argument("book")
    render.add_argument("--out", required=True)
    render.add_argument("--language")
    render.add_argument("--speed", type=float, default=1.0)
    render.add_argument("--chapters", help="e.g. 3 or 2-5")
    render.add_argument("--pronunciations", help="a book's pronunciation list (TSV)")
    voice_options(render)

    args = parser.parse_args(argv)
    from pagevoice.document import IngestError

    try:
        if args.command == "info":
            return cmd_info(args)
        if args.command == "download":
            return cmd_download(args)
        if args.command == "render":
            return cmd_render(args)
    except IngestError as exc:
        print(exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
