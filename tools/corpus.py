"""Golden corpus helper.

    uv run python tools/corpus.py fetch            # download public books by checksum
    uv run python tools/corpus.py check            # diff output against candidate/ pages
    uv run python tools/corpus.py check <book-id>
    uv run python tools/corpus.py draft <book-id> <page>...   # write candidate/ pages

`draft` writes what PageVoice currently produces into candidate/, for a human to correct
against the printed book and then move into expected/. Nothing here writes to expected/.
"""

import argparse
import difflib
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.corpus.golden import DOWNLOADS, books, normalise, render_page  # noqa: E402


def fetch() -> int:
    failed = 0
    for book in books():
        source = book.meta.get("source", "")
        if not source.startswith("http") or book.available():
            continue
        target = DOWNLOADS / book.id / book.path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Fetching {book.id} from {source}")
        request = urllib.request.Request(source, headers={"User-Agent": "PageVoice corpus"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != book.meta.get("sha256"):
            print(f"  checksum mismatch for {book.id}: got {digest}; not saved")
            failed += 1
            continue
        target.write_bytes(data)
    return 1 if failed else 0


def check(only: str | None) -> int:
    from pagevoice.ingest import read_book

    sys.stdout.reconfigure(encoding="utf-8")
    bad = good = 0
    for book in books():
        if only and book.id != only:
            continue
        pages = book.golden_pages("candidate")
        if not pages or not book.available():
            continue
        parsed = read_book(book.path)
        for number, path in pages.items():
            want = normalise(path.read_text(encoding="utf-8"))
            got = normalise(render_page(parsed, number, book.unit))
            if want == got:
                good += 1
                continue
            bad += 1
            print(f"--- {book.id} page {number}")
            for line in difflib.unified_diff(
                want.splitlines(), got.splitlines(), "candidate", "got", lineterm="", n=0
            ):
                print("   ", line[:200])
    print(f"{good} candidate pages match, {bad} differ")
    return 1 if bad else 0


def draft(book_id: str, numbers: list[int]) -> int:
    from pagevoice.ingest import read_book

    book = next((b for b in books() if b.id == book_id), None)
    if book is None or not book.available():
        print(f"{book_id}: not found or not downloaded")
        return 1
    parsed = read_book(book.path)
    folder = book.folder / "candidate"
    folder.mkdir(exist_ok=True)
    for number in numbers:
        text = render_page(parsed, number, book.unit)
        (folder / f"page-{number:03d}.txt").write_text(text + "\n", encoding="utf-8")
        print(f"wrote {folder.name}/page-{number:03d}.txt")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("book", nargs="?")
    draft_parser = sub.add_parser("draft")
    draft_parser.add_argument("book")
    draft_parser.add_argument("pages", nargs="+", type=int)
    args = parser.parse_args(argv)
    if args.command == "fetch":
        return fetch()
    if args.command == "check":
        return check(args.book)
    return draft(args.book, args.pages)


if __name__ == "__main__":
    raise SystemExit(main())
