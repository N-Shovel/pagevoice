"""Write the finished audiobook (SPEC §8, D17, D34).

- Default: one M4B (ffmpeg's ipod muxer) with a chapter list, cover art and metadata,
  encoded as 64 kbps mono AAC. A 10-hour book is about 290 MB.
- Option: one MP3 per chapter, with ID3 tags and the cover.

The chapter audio comes from the render cache. Output is written to a temporary name and
renamed when complete, so a cancelled or failed export never leaves a file that looks done.
After a successful export the book's render cache can be cleared (D26).
"""

import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pagevoice import __version__
from pagevoice.export.ffmpeg import Cancelled, FfmpegError, find_ffmpeg, run
from pagevoice.render.renderer import Renderer

log = logging.getLogger(__name__)

BITRATE = "64k"
COVER_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}
# ISO 639-1 to the ISO 639-2 codes audio tags use. A code table, not language rules.
ISO639_2 = {"en": "eng"}
EXPORT_RECORD = ".pagevoice-export.json"  # which MP3s PageVoice wrote here, per book
Progress = Callable[[str, float], None]  # (step, 0..1)


@dataclass(frozen=True)
class Metadata:
    title: str
    author: str = ""
    cover: bytes | None = None
    cover_type: str | None = None
    language: str = "en"

    @classmethod
    def from_book(cls, book) -> "Metadata":
        return cls(book.title, book.author, book.cover, book.cover_type, book.language)

    def cover_problem(self) -> str | None:
        """Why the cover can't go in the audiobook, in plain words; None if it can."""
        if self.cover and (self.cover_type or "").lower() not in COVER_EXT:
            kind = (self.cover_type or "unknown").split("/")[-1].upper()
            return f"The book's cover is a {kind} image, so the audiobook has no cover art."
        return None

    def language_code(self) -> str | None:
        return ISO639_2.get(self.language.strip().lower().replace("_", "-").split("-")[0])


def _escape_meta(value: str) -> str:
    """ffmetadata escaping: '=', ';', '#', '\\' and newlines take a backslash."""
    return re.sub(r"([=;#\\\n])", r"\\\1", value)


def _concat_line(path: Path) -> str:
    return "file '" + path.as_posix().replace("'", "'\\''") + "'"


def _work_folder(renderer: Renderer) -> tempfile.TemporaryDirectory:
    """Chapter audio for a whole book is about 1 GB: keep it next to the render cache,
    not in the system temp folder (which can be in RAM on Linux)."""
    return tempfile.TemporaryDirectory(prefix="export-", dir=renderer.cache.root)


def _write_chapters(
    renderer: Renderer, folder: Path, progress: Progress | None, stop: threading.Event | None
) -> list[tuple[Path, float]]:
    """Each chapter's audio as a FLAC file; returns (path, seconds)."""
    out = []
    total = len(renderer.book.chapters)
    for index in range(total):
        if stop is not None and stop.is_set():
            raise Cancelled
        path = folder / f"chapter-{index + 1:04d}.flac"
        out.append((path, renderer.write_chapter(index, path)))  # streamed: little memory
        if progress:
            progress("Preparing chapters", (index + 1) / total)
    return out


def _cover_file(meta: Metadata, folder: Path) -> Path | None:
    ext = COVER_EXT.get((meta.cover_type or "").lower())
    if not meta.cover or not ext:
        if problem := meta.cover_problem():
            log.warning(problem)
        return None
    path = folder / f"cover{ext}"
    path.write_bytes(meta.cover)
    return path


class TargetExists(FileExistsError):
    """The audiobook file is already there; replacing it needs overwrite=True."""

    def __init__(self, target: Path) -> None:
        super().__init__(f"{target} already exists. Choose another name, or replace it.")
        self.target = target


def _put_in_place(partial: Path, target: Path, attempts: int = 20) -> None:
    """Rename the finished .part file onto the target. On Windows that fails while a
    player has the target open: retry a moment, then remove the .part and say why."""
    for attempt in range(attempts):
        try:
            os.replace(partial, target)
            return
        except PermissionError:
            if attempt < attempts - 1:
                time.sleep(0.1)
    partial.unlink(missing_ok=True)
    raise FfmpegError(
        f"{target.name} is open in another program, so it can't be replaced. Close it "
        "(for example in your audio player) and export again."
    )


def _read_record(folder: Path) -> dict[str, list[str]]:
    try:
        data = json.loads((folder / EXPORT_RECORD).read_text(encoding="utf-8"))
        return {str(k): [str(n) for n in v] for k, v in data.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _write_record(folder: Path, record: dict[str, list[str]]) -> None:
    path = folder / EXPORT_RECORD
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _finish(renderer: Renderer, clear_cache: bool) -> None:
    if clear_cache:
        freed = renderer.cache.clear_book(renderer.book_id)
        log.info("Cleared %.1f MB of render cache for this book", freed / 2**20)


def export_m4b(
    renderer: Renderer,
    target: Path,
    *,
    meta: Metadata | None = None,
    progress: Progress | None = None,
    stop: threading.Event | None = None,
    clear_cache: bool = False,
    overwrite: bool = False,
) -> Path:
    """One M4B with chapters, cover and metadata. Every paragraph must be rendered.

    An existing target is replaced only with overwrite=True (TargetExists otherwise): it
    may be an audiobook the user bought. clear_cache deletes the book's render cache once
    the file is written (D26); leave it off while the book is still being edited."""
    target = Path(target)
    if target.exists() and not overwrite:
        raise TargetExists(target)
    find_ffmpeg()  # fail before minutes of chapter preparation, not after
    meta = meta or Metadata.from_book(renderer.book)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _work_folder(renderer) as tmp:
        folder = Path(tmp)
        chapters = _write_chapters(renderer, folder, progress, stop)
        (folder / "list.txt").write_text(
            "\n".join(_concat_line(p) for p, _ in chapters) + "\n", encoding="utf-8"
        )
        lines = [
            ";FFMETADATA1",
            f"title={_escape_meta(meta.title)}",
            f"album={_escape_meta(meta.title)}",
            f"artist={_escape_meta(meta.author)}",
            f"album_artist={_escape_meta(meta.author)}",
            "genre=Audiobook",
            "media_type=2",  # iTunes "stik" audiobook: players file it under audiobooks
            f"comment=Made with PageVoice {__version__}",
        ]
        start = 0
        for chapter, (_, seconds) in zip(renderer.book.chapters, chapters, strict=True):
            end = start + round(seconds * 1000)
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}"]
            lines.append(f"title={_escape_meta(chapter.title)}")
            start = end
        (folder / "meta.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

        args = ["-f", "concat", "-safe", "0", "-i", str(folder / "list.txt")]
        args += ["-f", "ffmetadata", "-i", str(folder / "meta.txt")]
        cover = _cover_file(meta, folder)
        if cover:
            args += ["-i", str(cover)]
        args += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
        if cover:
            args += ["-map", "2:v", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
        if language := meta.language_code():
            args += ["-metadata:s:a:0", f"language={language}"]
        partial = target.with_name(target.name + ".part")
        args += ["-c:a", "aac", "-b:a", BITRATE, "-ac", "1", "-movflags", "+faststart"]
        args += ["-f", "ipod", str(partial)]
        duration = sum(seconds for _, seconds in chapters)
        try:
            run(
                args,
                duration=duration,
                on_progress=(lambda f: progress("Encoding", f)) if progress else None,
                stop=stop,
            )
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        _put_in_place(partial, target)
    _finish(renderer, clear_cache)
    return target


def _safe_name(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    return text[:80] or "Chapter"


def export_mp3(
    renderer: Renderer,
    folder: Path,
    *,
    meta: Metadata | None = None,
    progress: Progress | None = None,
    stop: threading.Event | None = None,
    clear_cache: bool = False,
) -> list[Path]:
    """One MP3 per chapter, numbered so they sort in order, tagged, with the cover.

    Once all chapters are written, files an earlier export of this same book wrote here
    and this one didn't are removed (a renamed chapter's old file). A small record file in
    the folder says which files those are; nothing else in the folder is touched.
    If cancelled, the chapters already finished are kept: Cancelled.written lists them."""
    find_ffmpeg()
    meta = meta or Metadata.from_book(renderer.book)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    total = len(renderer.book.chapters)
    language = meta.language_code()
    with _work_folder(renderer) as tmp:
        work = Path(tmp)
        try:
            chapters = _write_chapters(renderer, work, progress, stop)
            cover = _cover_file(meta, work)
            for index, ((source, seconds), chapter) in enumerate(
                zip(chapters, renderer.book.chapters, strict=True), 1
            ):
                target = folder / f"{index:03d} - {_safe_name(chapter.title)}.mp3"
                partial = target.with_name(target.name + ".part")
                args = ["-i", str(source)]
                if cover:
                    args += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy"]
                    args += ["-disposition:v:0", "attached_pic", "-metadata:s:v", "title=Cover"]
                args += ["-c:a", "libmp3lame", "-b:a", BITRATE, "-ac", "1"]
                args += ["-id3v2_version", "3"]
                tags = [
                    ("title", chapter.title),
                    ("album", meta.title),
                    ("artist", meta.author),
                    ("album_artist", meta.author),
                    ("track", f"{index}/{total}"),
                    ("genre", "Audiobook"),
                ]
                if language:
                    tags.append(("language", language))
                for key, value in tags:
                    args += ["-metadata", f"{key}={value}"]
                args += ["-f", "mp3", str(partial)]
                try:
                    run(
                        args,
                        duration=seconds,
                        on_progress=(
                            (lambda f, i=index: progress("Encoding", (i - 1 + f) / total))
                            if progress
                            else None
                        ),
                        stop=stop,
                    )
                except BaseException:
                    partial.unlink(missing_ok=True)
                    raise
                _put_in_place(partial, target)
                written.append(target)
        except Cancelled as exc:
            exc.written = written
            raise
    # Remove only what an earlier export of this same book wrote here and this one didn't
    # (a renamed chapter's old file). Other files, other books' included, are never touched.
    record = _read_record(folder)
    names = {p.name for p in written}
    for name in record.get(renderer.book_id, []):
        if name not in names and (folder / name).is_file():
            (folder / name).unlink(missing_ok=True)
    record[renderer.book_id] = sorted(names)
    _write_record(folder, record)
    _finish(renderer, clear_cache)
    return written
