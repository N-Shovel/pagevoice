"""Write the finished audiobook (SPEC §8, D17, D34).

- Default: one M4B (ffmpeg's ipod muxer) with a chapter list, cover art and metadata,
  encoded as 64 kbps mono AAC. A 10-hour book is about 290 MB.
- Option: one MP3 per chapter, with ID3 tags and the cover.

The chapter audio comes from the render cache. Output is written to a temporary name and
renamed when complete, so a cancelled or failed export never leaves a file that looks done.
After a successful export the book's render cache can be cleared (D26).
"""

import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import soundfile

from pagevoice import __version__
from pagevoice.export.ffmpeg import Cancelled, find_ffmpeg, run
from pagevoice.render.renderer import Renderer
from pagevoice.voice.kokoro import SAMPLE_RATE

log = logging.getLogger(__name__)

BITRATE = "64k"
COVER_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png"}
# ISO 639-1 to the ISO 639-2 codes audio tags use. A code table, not language rules.
ISO639_2 = {"en": "eng"}
MP3_NAME = re.compile(r"^\d{3} - .*\.mp3$")
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
        audio = renderer.chapter_audio(index)
        path = folder / f"chapter-{index + 1:04d}.flac"
        soundfile.write(str(path), audio, SAMPLE_RATE, format="FLAC", subtype="PCM_16")
        out.append((path, len(audio) / SAMPLE_RATE))
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
) -> Path:
    """One M4B with chapters, cover and metadata. Every paragraph must be rendered.

    clear_cache deletes the book's render cache once the file is written (D26); leave it
    off while the book is still being edited."""
    find_ffmpeg()  # fail before minutes of chapter preparation, not after
    meta = meta or Metadata.from_book(renderer.book)
    target = Path(target)
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
        os.replace(partial, target)
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

    Once all chapters are written, earlier exports' "NNN - Title.mp3" files in the folder
    that weren't rewritten are removed, so a renamed chapter doesn't leave its old file.
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
                os.replace(partial, target)
                written.append(target)
        except Cancelled as exc:
            exc.written = written
            raise
    for old in folder.iterdir():
        if MP3_NAME.match(old.name) and old not in written:
            old.unlink(missing_ok=True)
    _finish(renderer, clear_cache)
    return written
