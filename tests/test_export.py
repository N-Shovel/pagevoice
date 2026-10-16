"""Export: M4B with chapters, cover and metadata, and MP3 per chapter (SPEC §8, D17, D18).

The unit tests replace ffmpeg with a fake that records what it was given. The real-encode
tests need the bundled ffmpeg (packaging/ffmpeg/build.sh, or PAGEVOICE_FFMPEG); they skip
without it, and the ffmpeg workflow runs them on CI with the binary it builds.
"""

import struct
import threading
import zlib
from pathlib import Path

import pytest

from pagevoice.document import Book, Chapter, Paragraph
from pagevoice.export import audiobook, ffmpeg
from pagevoice.export.audiobook import Metadata, export_m4b, export_mp3
from pagevoice.export.ffmpeg import Cancelled, FfmpegError, find_ffmpeg
from pagevoice.render.cache import RenderCache
from pagevoice.render.renderer import Renderer
from pagevoice.voice.kokoro import SAMPLE_RATE
from pagevoice.voice.manifest import PROPOSED, load_manifest
from tests.test_render import FakeVoice


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    pixels = zlib.compress(b"\x00\xc0\x40\x20")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def make_book() -> Book:
    def chapter(title: str, *texts: str) -> Chapter:
        heading = Paragraph.plain(title, kind="heading")
        return Chapter(title=title, paragraphs=[heading] + [Paragraph.plain(t) for t in texts])

    book = Book(
        title="The Lantern; a Tale = Light",
        chapters=[
            chapter("One: The Start", "It was dark.", "Then it wasn't."),
            chapter('Two / "Middle"?', "A longer paragraph that takes a little more time."),
            chapter("Three", "The end."),
        ],
    )
    book.author = "A. N. Author"
    book.cover = tiny_png()
    book.cover_type = "image/png"
    return book


@pytest.fixture
def renderer(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook, "find_ffmpeg", lambda: Path("ffmpeg"))
    voice = FakeVoice(manifest=load_manifest(PROPOSED))
    r = Renderer(make_book(), voice, RenderCache(tmp_path / "cache"), book_id="export")
    assert not r.run().failed
    return r


def chapter_seconds(r: Renderer) -> list[float]:
    return [len(r.chapter_audio(i)) / SAMPLE_RATE for i in range(len(r.book.chapters))]


# --- without ffmpeg -------------------------------------------------------------------


class FakeRun:
    """Stands in for ffmpeg.run: records the arguments and the files they point at."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.files: dict[str, str] = {}
        self.fail = fail

    def __call__(self, args, *, duration=None, on_progress=None, stop=None):
        self.calls.append(list(args))
        for arg in args:
            if arg.endswith((".txt",)):
                self.files[Path(arg).name] = Path(arg).read_text(encoding="utf-8")
        if on_progress:
            on_progress(1.0)
        if self.fail:
            Path(args[-1]).write_bytes(b"half")
            raise FfmpegError("Making the audio file failed.")
        Path(args[-1]).write_bytes(b"audio")


def test_m4b_metadata_and_chapter_times(renderer, tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    target = export_m4b(renderer, tmp_path / "out" / "book.m4b")
    assert target.read_bytes() == b"audio"
    meta = fake.files["meta.txt"].splitlines()
    assert meta[0] == ";FFMETADATA1"
    assert r"title=The Lantern\; a Tale \= Light" in meta
    assert "artist=A. N. Author" in meta
    starts = [int(line[6:]) for line in meta if line.startswith("START=")]
    ends = [int(line[4:]) for line in meta if line.startswith("END=")]
    seconds = chapter_seconds(renderer)
    assert starts[0] == 0 and starts[1:] == ends[:-1]  # back to back, no gaps
    assert [e - s for s, e in zip(starts, ends, strict=True)] == [round(s * 1000) for s in seconds]
    titles = [line for line in meta if line.startswith("title=")][1:]
    assert titles == ["title=One: The Start", 'title=Two / "Middle"?', "title=Three"]
    args = fake.calls[0]
    assert "attached_pic" in args and "ffmetadata" in args
    assert fake.files["list.txt"].count("file '") == 3


def test_failed_export_leaves_no_file(renderer, tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook, "run", FakeRun(fail=True))
    with pytest.raises(FfmpegError):
        export_m4b(renderer, tmp_path / "book.m4b")
    assert list(tmp_path.glob("book.m4b*")) == []


def test_cancel_before_encoding(renderer, tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        export_m4b(renderer, tmp_path / "book.m4b", stop=stop)
    assert not fake.calls and not (tmp_path / "book.m4b").exists()


def test_unrendered_book_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook, "run", FakeRun())
    monkeypatch.setattr(audiobook, "find_ffmpeg", lambda: Path("ffmpeg"))
    voice = FakeVoice(manifest=load_manifest(PROPOSED))
    r = Renderer(make_book(), voice, RenderCache(tmp_path / "cache"), book_id="x")
    with pytest.raises(LookupError):
        export_m4b(r, tmp_path / "book.m4b")


def test_mp3_names_and_tags(renderer, tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    written = export_mp3(renderer, tmp_path / "mp3")
    assert [p.name for p in written] == [
        "001 - One The Start.mp3",
        "002 - Two  Middle.mp3",
        "003 - Three.mp3",
    ]
    first = fake.calls[0]
    assert "track=1/3" in first and "title=One: The Start" in first
    assert "album=The Lantern; a Tale = Light" in first


def test_ffmpeg_is_never_looked_up_on_path(tmp_path, monkeypatch):
    monkeypatch.delenv("PAGEVOICE_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg, "REPO", tmp_path)  # no bundled build here
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / ffmpeg.EXE).write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    with pytest.raises(FfmpegError, match="Reinstall PageVoice"):
        find_ffmpeg()


# --- with the bundled ffmpeg ----------------------------------------------------------


@pytest.fixture
def real_ffmpeg():
    """The real binary. (The renderer fixture stubs only the exporters' up-front check;
    ffmpeg.run always finds the real one.)"""
    try:
        return find_ffmpeg()
    except FfmpegError:
        pytest.skip("bundled ffmpeg not built (packaging/ffmpeg/build.sh)")


def test_real_m4b_has_chapters_cover_and_tags(real_ffmpeg, renderer, tmp_path):
    from mutagen.mp4 import MP4, Atoms

    progress = []
    target = export_m4b(
        renderer, tmp_path / "book.m4b", progress=lambda step, f: progress.append((step, f))
    )
    audio = MP4(str(target))
    assert audio.tags["\xa9nam"] == ["The Lantern; a Tale = Light"]
    assert audio.tags["\xa9ART"] == ["A. N. Author"]
    assert audio.tags["\xa9gen"] == ["Audiobook"]
    assert audio.tags["stik"] == [2]  # audiobook media type
    assert len(audio.tags["covr"]) == 1
    assert audio.info.channels == 1
    assert audio.info.length == pytest.approx(sum(chapter_seconds(renderer)), abs=0.2)
    with target.open("rb") as fh:  # QuickTime chapter track (Apple Books, iOS)
        moov = Atoms(fh)[b"moov"]
    traks = moov.findall(b"trak")
    assert any(tref.findall(b"chap") for trak in traks for tref in trak.findall(b"tref"))
    chapters = audio.chapters  # Nero "chpl" chapters (most other players)
    assert [c.title for c in chapters] == ["One: The Start", 'Two / "Middle"?', "Three"]
    seconds = chapter_seconds(renderer)
    assert chapters[1].start == pytest.approx(seconds[0], abs=0.05)
    assert progress and progress[-1][0] == "Encoding" and progress[-1][1] > 0.9
    assert not list(tmp_path.glob("*.part"))


def test_real_mp3_per_chapter(real_ffmpeg, renderer, tmp_path):
    from mutagen.mp3 import MP3

    written = export_mp3(renderer, tmp_path / "mp3", meta=Metadata.from_book(renderer.book))
    assert len(written) == 3
    for index, (path, seconds) in enumerate(zip(written, chapter_seconds(renderer), strict=True)):
        audio = MP3(str(path))
        assert audio.tags["TIT2"].text[0] == renderer.book.chapters[index].title
        assert audio.tags["TALB"].text[0] == "The Lantern; a Tale = Light"
        assert audio.tags["TRCK"].text[0] == f"{index + 1}/3"
        assert audio.tags.getall("APIC")
        assert audio.info.length == pytest.approx(seconds, abs=0.2)


def test_missing_ffmpeg_fails_before_preparing_chapters(renderer, tmp_path, monkeypatch):
    def missing():
        raise FfmpegError(ffmpeg.MISSING)

    monkeypatch.setattr(audiobook, "find_ffmpeg", missing)
    monkeypatch.setattr(audiobook, "_write_chapters", lambda *a: pytest.fail("prepared chapters"))
    with pytest.raises(FfmpegError):
        export_m4b(renderer, tmp_path / "book.m4b")
    with pytest.raises(FfmpegError):
        export_mp3(renderer, tmp_path / "mp3")


def test_cache_is_cleared_only_when_asked(renderer, tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook, "run", FakeRun())
    keys = [item.key for item in renderer.items]
    export_m4b(renderer, tmp_path / "a.m4b")
    assert all(renderer.cache.has(k) for k in keys)
    export_m4b(renderer, tmp_path / "b.m4b", clear_cache=True)
    assert not any(renderer.cache.has(k) for k in keys)
    assert renderer.cache.book_keys("export") == set()


def test_work_files_go_next_to_the_cache_not_system_temp(renderer, tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    export_m4b(renderer, tmp_path / "a.m4b")
    args = fake.calls[0]
    concat_list = Path(args[args.index("concat") + 4])
    assert concat_list.name == "list.txt"
    assert concat_list.is_relative_to(renderer.cache.root)
    assert not list(renderer.cache.root.glob("export-*"))  # cleaned up


def test_language_and_media_type(renderer, tmp_path, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    export_m4b(renderer, tmp_path / "a.m4b")
    assert "language=eng" in fake.calls[0]
    assert "media_type=2" in fake.files["meta.txt"].splitlines()
    export_mp3(renderer, tmp_path / "mp3")
    assert "language=eng" in fake.calls[1]
    assert Metadata("t", language="en-GB").language_code() == "eng"
    assert Metadata("t", language="xx").language_code() is None


def test_unsupported_cover_is_reported(renderer, tmp_path, monkeypatch, caplog):
    fake = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake)
    meta = Metadata("t", cover=b"GIF89a", cover_type="image/gif")
    assert "GIF" in meta.cover_problem()
    assert Metadata("t", cover=tiny_png(), cover_type="image/png").cover_problem() is None
    export_m4b(renderer, tmp_path / "a.m4b", meta=meta)
    assert "attached_pic" not in fake.calls[0]
    assert "no cover art" in caplog.text


def test_mp3_reexport_removes_old_chapter_files_only(renderer, tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook, "run", FakeRun())
    folder = tmp_path / "mp3"
    folder.mkdir()
    (folder / "004 - Old Chapter.mp3").write_bytes(b"old")
    (folder / "notes.txt").write_text("mine")
    (folder / "My favourite.mp3").write_bytes(b"mine")
    written = export_mp3(renderer, folder)
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [p.name for p in written] + ["notes.txt", "My favourite.mp3"]
    )


def test_cancelled_mp3_export_keeps_finished_chapters(renderer, tmp_path, monkeypatch):
    fake = FakeRun()

    def run(args, *, stop=None, **kwargs):
        if stop.is_set():
            raise Cancelled
        fake(args, **kwargs)
        stop.set()  # the user stops after the first chapter is encoded

    monkeypatch.setattr(audiobook, "run", run)
    with pytest.raises(Cancelled) as info:
        export_mp3(renderer, tmp_path / "mp3", stop=threading.Event())
    assert [p.name for p in info.value.written] == ["001 - One The Start.mp3"]
    assert [p.name for p in (tmp_path / "mp3").iterdir()] == ["001 - One The Start.mp3"]


def test_env_override_is_ignored_in_the_installed_app(tmp_path, monkeypatch):
    fake = tmp_path / ffmpeg.EXE
    fake.write_bytes(b"")
    monkeypatch.setenv("PAGEVOICE_FFMPEG", str(fake))
    monkeypatch.setattr(ffmpeg, "REPO", tmp_path / "nowhere")
    assert find_ffmpeg() == fake  # development
    monkeypatch.setattr(ffmpeg.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ffmpeg.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    with pytest.raises(FfmpegError):
        find_ffmpeg()


class FakeProcess:
    """Stands in for the ffmpeg process: two progress lines, and it runs until stopped."""

    last: "FakeProcess"

    def __init__(self, *args, **kwargs):
        self.stdout = iter(["out_time_us=500000\n", "out_time_us=900000\n"])
        self.stderr = iter([])
        self.terminated = False
        FakeProcess.last = self

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    kill = terminate

    def wait(self, timeout=None):
        return 0


def test_ffmpeg_is_stopped_when_a_callback_fails(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", FakeProcess)

    def broken(_fraction):
        raise RuntimeError("the window was closed")

    with pytest.raises(RuntimeError):
        ffmpeg.run(["x"], duration=1.0, on_progress=broken)
    assert FakeProcess.last.terminated


def test_cancel_stops_ffmpeg(monkeypatch):
    monkeypatch.setattr(ffmpeg, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", FakeProcess)
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        ffmpeg.run(["x"], stop=stop)
    assert FakeProcess.last.terminated
