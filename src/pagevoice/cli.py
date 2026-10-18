"""Small command line for driving the engine during development and testing.

pagevoice info BOOK                      chapters, flags and removals
pagevoice download                       first-run model download (checksum-verified)
pagevoice render BOOK --out DIR          render to the cache, write chapter audio
pagevoice export BOOK --out FILE.m4b     render (resuming), then write the audiobook
                 [--format mp3]          or one MP3 per chapter into a folder
"""

import argparse
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


def _render(args):
    """Render the book (resuming from the cache). Returns (renderer, result) or an exit code."""
    from pagevoice import project
    from pagevoice.ingest import read_book
    from pagevoice.pronounce.store import entries_for
    from pagevoice.render.cache import RenderCache
    from pagevoice.render.renderer import Renderer, RenderSettings
    from pagevoice.voice.engine import VoiceNotReady

    path = Path(args.book)
    book_id = project.book_id(path)
    book = project.load(book_id) if not args.language else None
    if book:
        print("Using the review saved in the app for this book.")
    else:
        book = read_book(path, language=args.language)
    if args.chapters:
        first, _, last = args.chapters.partition("-")
        book.chapters = book.chapters[int(first) - 1 : int(last or first)]
    renderer = Renderer(
        book,
        _voice(args),
        RenderCache(),
        book_id=book_id,
        settings=RenderSettings(speed=args.speed),
        pronunciations=entries_for(
            Path(args.pronunciations)
            if args.pronunciations
            else project.pronunciations_path(book_id)
        ),
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
    for item, warning in result.warnings:
        print(f"  chapter {item.chapter + 1}, paragraph {item.paragraph + 1}: {warning}")
        print(f"    {item.spoken[:100]}")
    return renderer, result


def cmd_render(args) -> int:
    from pagevoice.audio import write_wav
    from pagevoice.voice.kokoro import SAMPLE_RATE

    rendered = _render(args)
    if isinstance(rendered, int):
        return rendered
    renderer, result = rendered
    book = renderer.book
    out = Path(args.out)
    incomplete = False
    for index, chapter in enumerate(book.chapters):
        target = out / f"{index + 1:03d}.wav"
        try:
            audio = renderer.chapter_audio(index)
        except LookupError as exc:  # a paragraph failed: write the other chapters anyway
            print(f"  skipped: {exc}", file=sys.stderr)
            incomplete = True
            continue
        write_wav(target, audio, SAMPLE_RATE)
        print(f"  {target}  {chapter.title[:60]}")
    return 1 if result.failed or incomplete else 0


def cmd_export(args) -> int:
    from pagevoice.export.audiobook import Metadata, TargetExists, export_m4b, export_mp3
    from pagevoice.export.ffmpeg import Cancelled, FfmpegError

    rendered = _render(args)
    if isinstance(rendered, int):
        return rendered
    renderer, result = rendered
    if result.failed:
        print(
            f"{len(result.failed)} paragraphs failed to render, so the audiobook can't be "
            "made yet. Run the same command again to retry them.",
            file=sys.stderr,
        )
        return 1

    def progress(step: str, fraction: float) -> None:
        print(f"\r  {step}: {fraction:4.0%}   ", end="", flush=True)

    meta = Metadata.from_book(renderer.book)
    if problem := meta.cover_problem():
        print(f"  {problem}")
    stop = threading.Event()
    # With --chapters only part of the book is exported: keep the rest of its audio.
    clear = not args.keep_cache and not args.chapters
    options = dict(meta=meta, progress=progress, stop=stop, clear_cache=clear)
    try:
        if args.format == "mp3":
            written = export_mp3(renderer, Path(args.out), **options)
        else:
            written = [export_m4b(renderer, Path(args.out), overwrite=args.overwrite, **options)]
    except TargetExists as exc:
        print(f"\n{exc} Add --overwrite to replace it.", file=sys.stderr)
        return 2
    except FfmpegError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2
    except LookupError:  # a cached paragraph went missing or unreadable since rendering
        print(
            "\nSome rendered audio is missing from the cache. Run the same command again: "
            "it renders what's missing, then exports.",
            file=sys.stderr,
        )
        return 1
    except (KeyboardInterrupt, Cancelled) as exc:
        stop.set()
        kept = getattr(exc, "written", [])
        if kept:
            print(f"\nStopped. The {len(kept)} chapters finished before that were kept.")
        else:
            print("\nStopped. No audiobook file was written.")
        return 130
    print()
    for path in written:
        print(f"  {path}")
    if clear:
        print("  The book's render cache was cleared. Use --keep-cache to keep it for edits.")
    return 0


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

    def book_options(p):
        p.add_argument("book")
        p.add_argument("--language")
        p.add_argument("--speed", type=float, default=1.0)
        p.add_argument("--chapters", help="e.g. 3 or 2-5")
        p.add_argument("--pronunciations", help="a book's pronunciation list (TSV)")
        voice_options(p)

    render = sub.add_parser("render", help="render a book to chapter audio files")
    render.add_argument("--out", required=True, help="folder for the chapter WAV files")
    book_options(render)
    export = sub.add_parser("export", help="render a book and write the audiobook")
    export.add_argument("--out", required=True, help="the .m4b file, or a folder for MP3s")
    export.add_argument("--format", default="m4b", choices=["m4b", "mp3"])
    export.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the .m4b if it already exists",
    )
    export.add_argument(
        "--keep-cache",
        action="store_true",
        help="keep the book's rendered audio after export (for further edits)",
    )
    book_options(export)

    args = parser.parse_args(argv)
    from pagevoice.document import IngestError

    try:
        if args.command == "info":
            return cmd_info(args)
        if args.command == "download":
            return cmd_download(args)
        if args.command == "render":
            return cmd_render(args)
        if args.command == "export":
            return cmd_export(args)
    except IngestError as exc:
        print(exc, file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
