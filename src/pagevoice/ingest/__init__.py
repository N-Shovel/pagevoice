"""Read EPUB, text PDFs and TXT into a Book. MOBI/AZW3 and DRM files are refused plainly."""

from pathlib import Path

from pagevoice.document import Book, IngestError

CALIBRE = (
    "PageVoice can't read {kind} files. Convert the book to EPUB with Calibre "
    "(calibre-ebook.com), then open the EPUB."
)


def read_book(path: Path, *, language: str | None = None) -> Book:
    """Read any supported file. Raises IngestError with a plain message otherwise.

    language overrides what the file says; without either, the book is English.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".txt":
        from pagevoice.ingest.txt import read_txt

        return read_txt(path, language=language)
    if suffix == ".epub":
        from pagevoice.ingest.epub import read_epub

        return read_epub(path, language=language)
    if suffix == ".pdf":
        from pagevoice.ingest.pdf import read_pdf

        return read_pdf(path, language=language)
    if suffix in (".mobi", ".azw", ".azw3", ".kfx"):
        raise IngestError(CALIBRE.format(kind=suffix[1:].upper()))
    raise IngestError(f"PageVoice can't read {suffix or 'this kind of'} files yet.")
