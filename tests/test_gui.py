"""The desktop app, driven headless (Qt's offscreen platform) with a fake voice.

Covers M4's path: open → review (dimmed removals, restore, chapter edits) → render with
progress, pause and resume → export, with all slow work off the UI thread.
"""

import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="the gui extra isn't installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from pagevoice import project  # noqa: E402
from pagevoice.export import audiobook  # noqa: E402
from pagevoice.pronounce.lexicon import Entry, LexiconError, load  # noqa: E402
from pagevoice.render.cache import RenderCache  # noqa: E402
from pagevoice.voice.manifest import PROPOSED, load_manifest  # noqa: E402
from pagevoice_gui import playback, tasks  # noqa: E402
from pagevoice_gui.main_window import OPEN, PRODUCE, REVIEW, MainWindow  # noqa: E402
from pagevoice_gui.produce import duration_text, voice_label  # noqa: E402
from pagevoice_gui.pronunciations import PronunciationDialog  # noqa: E402
from tests.test_export import FakeRun  # noqa: E402
from tests.test_render import FakeVoice  # noqa: E402

CORPUS = Path(__file__).parent / "corpus" / "public"
PDF = CORPUS / "trap-lantern" / "book.pdf"


class ReadyVoice(FakeVoice):
    def ready(self) -> bool:
        return True


def wait_until(condition, timeout: float = 20.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting for the UI")
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(qapp, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    qapp.setOrganizationName("PageVoiceTests")
    monkeypatch.setenv("PAGEVOICE_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("PAGEVOICE_DATA_DIR", str(tmp_path / "data"))
    shown = []
    for name in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, _n=name, **k: shown.append((_n, a)))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    return shown


@pytest.fixture
def window(env, tmp_path):
    voices = []

    def factory(name, provider):
        voice = ReadyVoice(manifest=load_manifest(PROPOSED), voice=name)
        voices.append(voice)
        return voice

    w = MainWindow(factory, ["af_heart", "bm_george"], RenderCache(tmp_path / "cache"))
    w.made_voices = voices
    yield w
    w.produce_page.stop_work()
    tasks.wait_for_all(5000)
    QApplication.processEvents()
    w.deleteLater()


def open_book(window, path: Path) -> None:
    window.load_book(path)
    wait_until(lambda: window.session is not None)


def test_tasks_report_on_the_ui_thread(qapp):
    seen = {}
    main = threading.current_thread()

    def work(report):
        seen["worker"] = threading.current_thread() is not main
        report("halfway")
        return 42

    tasks.run_task(
        work,
        on_progress=lambda v: seen.setdefault("progress", threading.current_thread() is main),
        on_done=lambda v: seen.setdefault("done", (v, threading.current_thread() is main)),
    )
    wait_until(lambda: "done" in seen)
    assert seen == {"worker": True, "progress": True, "done": (42, True)}


def test_failures_reach_the_ui_thread(qapp):
    seen = []
    tasks.run_task(lambda r: 1 / 0, on_failed=seen.append)
    wait_until(lambda: seen)
    assert isinstance(seen[0], ZeroDivisionError)


def test_pdf_opens_in_review_txt_skips_it(window, tmp_path):
    open_book(window, PDF)
    assert window.stack.currentIndex() == REVIEW
    assert window.review_page.chapters.count() == len(window.session.book.chapters)
    txt = tmp_path / "story.txt"
    txt.write_text("A Story\n\nOnce upon a time.\n\nThe end.\n", encoding="utf-8")
    open_book_again = window.session
    window.load_book(txt)
    wait_until(lambda: window.session is not open_book_again)
    assert window.stack.currentIndex() == PRODUCE  # review is optional for TXT and EPUB


def test_unreadable_file_gets_a_plain_message(window, env, tmp_path):
    bad = tmp_path / "book.mobi"
    bad.write_bytes(b"not a book")
    window.load_book(bad)
    wait_until(lambda: env)
    assert window.session is None and window.stack.currentIndex() == OPEN
    kind, args = env[0]
    assert kind == "warning" and "Traceback" not in args[2]


def test_removals_are_dimmed_and_restorable(window):
    open_book(window, PDF)
    review = window.review_page
    for row in range(review.chapters.count()):  # find a chapter with removals
        review.chapters.setCurrentRow(row)
        if review._spans:
            break
    ref, (span, _block) = next(iter(review._spans.items()))
    assert span.removed and "line-through" in review.text.toHtml()
    review._hovered(QUrl(f"span:{ref}"))
    assert "Removed as" in review.hint.text()
    document = review.text.document()
    review._anchor_clicked(QUrl(f"span:{ref}"))
    assert review.text.document() is document  # restyled in place, not rebuilt
    assert span.restored and "brought back" in review.summary.text()
    assert span.text.strip() in review.text.toPlainText()
    review._anchor_clicked(QUrl(f"span:{ref}"))  # and back again
    assert span.removed and "brought back" not in review.summary.text()
    review._anchor_clicked(QUrl(f"span:{ref}"))
    window.session.save_now()
    book_id = window.session.book_id
    wait_until(lambda: (b := project.load(book_id)) and any(s.restored for s in b.removals))


def test_saved_review_comes_back_when_reopened(window):
    open_book(window, PDF)
    window.review_page.rename("A New Name")
    window.session.save_now()
    first = window.session
    wait_until(lambda: (b := project.load(first.book_id)) and b.chapters[0].title == "A New Name")
    window.load_book(PDF)
    wait_until(lambda: window.session is not first)
    assert window.session.resumed and window.session.book.chapters[0].title == "A New Name"


def test_chapter_edits(window):
    open_book(window, PDF)
    review = window.review_page
    count = review.chapters.count()
    review.chapters.setCurrentRow(0)
    review.merge()
    assert review.chapters.count() == count - 1
    review.split(2, title="Split Off")
    assert review.chapters.count() == count
    assert window.session.book.chapters[1].title == "Split Off"
    assert review.chapters.currentRow() == 1


def test_split_asks_for_a_title_when_there_is_no_heading(window, monkeypatch):
    open_book(window, PDF)
    review = window.review_page
    review.chapters.setCurrentRow(2)
    chapter = window.session.book.chapters[2]
    plain = next(i for i, p in enumerate(chapter.paragraphs) if i and p.kind != "heading")
    asked = []
    monkeypatch.setattr(
        "pagevoice_gui.review.QInputDialog.getText",
        lambda *a, **k: asked.append(k.get("text")) or ("The Middle", True),
    )
    review.split(plain)
    assert asked == ["Chapter 4"]
    assert window.session.book.chapters[3].title == "The Middle"


def test_long_chapters_are_shown_in_parts(window, tmp_path):
    txt = tmp_path / "long.txt"
    txt.write_text("\n\n".join(f"Paragraph number {n}." for n in range(450)), encoding="utf-8")
    open_book(window, txt)
    window.show_step(REVIEW)
    review = window.review_page
    assert review.parts_bar.isVisibleTo(review)
    assert "Part 1 of 3" in review.part_label.text()
    assert "Paragraph number 199." in review.text.toPlainText()
    assert "Paragraph number 200." not in review.text.toPlainText()
    review._turn(1)
    assert "Paragraph number 200." in review.text.toPlainText()


def test_wrongly_labelled_book_can_be_read_as_english(window, env, tmp_path, monkeypatch):
    import pagevoice.ingest
    from pagevoice.cleanup.language import LanguageNotSupported

    calls, real_read_book = [], pagevoice.ingest.read_book

    def fake_read_book(path, language=None):
        calls.append(language)
        if language is None:
            raise LanguageNotSupported("French")
        return real_read_book(path, language=language)

    monkeypatch.setattr("pagevoice.ingest.read_book", fake_read_book)
    txt = tmp_path / "book.txt"
    txt.write_text("Title\n\nSome English text.\n", encoding="utf-8")
    open_book(window, txt)
    assert calls == [None, "en"] and window.session.book.language == "en"


def test_unreadable_saved_review_is_reported(window, env, tmp_path):
    txt = tmp_path / "book.txt"
    txt.write_text("Title\n\nText.\n", encoding="utf-8")
    book_id = project.book_id(txt)
    project.projects_dir().mkdir(parents=True, exist_ok=True)
    (project.projects_dir() / f"{book_id}.json").write_text("{broken", encoding="utf-8")
    open_book(window, txt)
    wait_until(lambda: env)
    assert env[-1][0] == "information" and "couldn't be read" in env[-1][1][2]
    assert (project.projects_dir() / f"{book_id}.json.bak").exists()


def test_render_pause_resume_and_export(window, monkeypatch, tmp_path):
    fake_run = FakeRun()
    monkeypatch.setattr(audiobook, "run", fake_run)
    monkeypatch.setattr(audiobook, "find_ffmpeg", lambda: Path("ffmpeg"))
    open_book(window, PDF)
    window.show_step(PRODUCE)
    page = window.produce_page
    page.pause.set()  # start paused: nothing renders until resumed
    page.start_render()
    page.pause.set()
    wait_until(lambda: page.renderer is not None)
    assert page.pause_button.isEnabled() and page.stop_button.isEnabled()
    assert not window.steps.button(REVIEW).isEnabled()  # no review edits while rendering
    time.sleep(0.3)
    QApplication.processEvents()
    assert sum(v.calls for v in window.made_voices) == 0
    page.toggle_pause()  # resume
    wait_until(lambda: not page._busy, timeout=60)
    assert "Everything is rendered" in page.status.text()
    assert page.progress.value() == page.progress.maximum()
    assert window.steps.button(REVIEW).isEnabled()

    keys = [i.key for i in page.renderer.items]
    page.target.setText(str(tmp_path / "out" / "book.m4b"))
    page.start_export()
    wait_until(lambda: not page._busy)
    assert (tmp_path / "out" / "book.m4b").read_bytes() == b"audio"
    assert "Done" in page.export_status.text()
    assert all(page.cache.has(k) for k in keys)  # kept while the book may still change
    assert page.free_button.isVisibleTo(page)
    page.free_cache()
    wait_until(lambda: "Freed" in page.export_status.text())
    assert not any(page.cache.has(k) for k in keys)


def test_export_refuses_unrendered_changes(window, monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook, "run", FakeRun())
    monkeypatch.setattr(audiobook, "find_ffmpeg", lambda: Path("ffmpeg"))
    open_book(window, PDF)
    page = window.produce_page
    page.target.setText(str(tmp_path / "book.m4b"))
    page.start_export()
    wait_until(lambda: not page._busy)
    assert "Press Render first" in page.export_status.text()
    assert not (tmp_path / "book.m4b").exists()


def test_stop_then_render_carries_on(window):
    open_book(window, PDF)
    page = window.produce_page
    page.pause.set()
    page.start_render()
    page.pause.set()
    wait_until(lambda: page.renderer is not None)
    page.stop_work()
    wait_until(lambda: not page._busy)
    assert "carry on" in page.status.text()
    page.start_render()
    wait_until(lambda: not page._busy, timeout=60)
    assert "Everything is rendered" in page.status.text()


def test_first_run_offers_the_download(window, monkeypatch):
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No
    )
    monkeypatch.setattr(ReadyVoice, "ready", lambda self: False)
    open_book(window, PDF)
    window.produce_page.start_render()
    wait_until(lambda: asked)
    assert "download its voice once" in asked[0]
    wait_until(lambda: not window.produce_page._busy)


def test_download_is_busy_work_then_resumes_what_asked(window, monkeypatch):
    downloaded = threading.Event()
    state = {"ready": False}
    monkeypatch.setattr(ReadyVoice, "ready", lambda self: state["ready"])

    def download(self, progress=None, *, use_source=False):
        assert use_source is False  # tests never pass the dev flag: our release only (D9)
        assert window.produce_page.busy  # no second download, no quitting silently
        progress(50, 100)
        state["ready"] = True
        downloaded.set()

    monkeypatch.setattr(ReadyVoice, "download", download)
    open_book(window, PDF)
    window.produce_page.start_render()
    wait_until(downloaded.is_set)
    wait_until(lambda: "Everything is rendered" in window.produce_page.status.text(), 60)


def test_damaged_download_gets_a_plain_message(window, env, monkeypatch):
    from pagevoice.voice.download import ChecksumError

    monkeypatch.setattr(ReadyVoice, "ready", lambda self: False)

    def download(self, progress=None, *, use_source=False):
        raise ChecksumError("kokoro.onnx from https://x doesn't match (sha256 abc)")

    monkeypatch.setattr(ReadyVoice, "download", download)
    open_book(window, PDF)
    window.produce_page.start_render()
    wait_until(lambda: any("damaged" in str(a) for _k, a in env))
    assert not any("sha256" in str(a) for _k, a in env)


def test_voices_are_shared_and_checked_once(window):
    first = window.voice_factory("af_heart", "cpu")
    assert window.voice_factory("af_heart", "cpu") is first
    assert window.voice_factory("bm_george", "cpu") is not first


def test_cache_cap_is_a_setting(window, monkeypatch):
    from pagevoice_gui.settings_dialog import GB, SettingsDialog, cache_cap_bytes

    dialog = SettingsDialog(window.cache, busy=False)
    wait_until(lambda: "GB" in dialog.used.text())
    dialog.cap.setValue(12)
    dialog.accept()
    assert window.cache.cap_bytes == 12 * GB and cache_cap_bytes() == 12 * GB


def test_notes_setting_reaches_the_review(window, tmp_path):
    from pagevoice.document import Book, Chapter, Paragraph
    from pagevoice_gui.session import Session

    book = Book("B", chapters=[Chapter("One", [Paragraph.plain("Body.")],
                                       [Paragraph.plain("A note.", kind="note")])])  # fmt: skip
    window.set_session(Session(book, "notes", tmp_path / "b.txt"))
    window.show_step(REVIEW)
    assert "read at the end" in window.review_page.text.toPlainText()
    window.produce_page.read_notes.setChecked(False)
    assert "not read" in window.review_page.text.toPlainText()
    window.produce_page.read_notes.setChecked(True)


def test_pronunciation_dialog_saves_both_lists(window, tmp_path):
    book_list, global_list = tmp_path / "book.tsv", tmp_path / "global.tsv"
    previews = []
    dialog = PronunciationDialog(book_list, global_list, lambda t, e: previews.append((t, e)))
    book_table = dialog.paths[1][1]
    book_table.add(Entry("Hermione", "her-my-oh-nee"))
    book_table.table.setCurrentCell(0, 0)
    book_table.play()
    assert previews[0][0] == "Hermione"
    dialog.global_table.add(Entry("Polish", "poh-lish", case_sensitive=True))
    dialog.accept()
    assert [e.word for e in load(book_list)] == ["Hermione"]
    assert load(global_list)[0].case_sensitive


def test_import_reports_words_already_listed(window, env, tmp_path, monkeypatch):
    shared = tmp_path / "series.tsv"
    shared.write_text("Darcy\tdar-see\nBingley\tbing-lee\n", encoding="utf-8")
    dialog = PronunciationDialog(None, tmp_path / "g.tsv", lambda t, e: None)
    dialog.global_table.add(Entry("Darcy", "dar-sy"))
    monkeypatch.setattr(
        "pagevoice_gui.pronunciations.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(shared), ""),
    )
    dialog.global_table.import_file()
    words = [(e.word, e.sounds_like) for e in dialog.global_table.entries()]
    assert words == [("Darcy", "dar-sy"), ("Bingley", "bing-lee")]
    assert "already in this list" in env[-1][1][2]


def test_pronunciation_rows_are_checked(window, tmp_path):
    dialog = PronunciationDialog(tmp_path / "b.tsv", tmp_path / "g.tsv", lambda t, e: None)
    dialog.global_table.add(Entry("Word"))  # no "sounds like" or phonemes
    with pytest.raises(LexiconError, match="Row 1"):
        dialog.global_table.entries()
    dialog.accept()
    assert not (tmp_path / "g.tsv").exists()


def test_labels():
    assert voice_label("af_heart") == "Heart (American, female)"
    assert voice_label("bm_george") == "George (British, male)"
    assert voice_label("odd") == "odd"
    assert duration_text(30) == "under a minute"
    assert duration_text(3 * 3600 + 5 * 60) == "3 h 5 min"


def test_linux_player_is_found(monkeypatch, tmp_path):
    monkeypatch.setattr(playback.shutil, "which", lambda name: name == "paplay" or None)
    assert playback.player_command(tmp_path / "a.wav") == ["paplay", str(tmp_path / "a.wav")]
    monkeypatch.setattr(playback.shutil, "which", lambda name: None)
    assert playback.player_command(tmp_path / "a.wav") is None


def test_a_list_that_cant_be_read_is_never_saved_over(window, env, tmp_path):
    """Review finding 2: Save used to write the empty table over the unreadable file."""
    broken = tmp_path / "book.tsv"
    original = "Anne\tAnn\t\tmaybe\n"  # "maybe" isn't yes or no
    broken.write_text(original, encoding="utf-8")
    dialog = PronunciationDialog(broken, tmp_path / "g.tsv", lambda t, e: None)
    assert env and "won't be changed" in env[-1][1][2]
    dialog.global_table.add(Entry("Polish", "poh-lish"))
    dialog.accept()
    assert broken.read_text(encoding="utf-8") == original
    assert load(tmp_path / "g.tsv")[0].word == "Polish"  # the readable list still saves


def _button(widget, text):
    from PySide6.QtWidgets import QPushButton

    return next(b for b in widget.findChildren(QPushButton) if b.text() == text)


def test_real_buttons_move_between_steps(window, monkeypatch):
    """Click the actual buttons (not the methods): a button wired straight to a signal
    fails only when clicked ("native Qt signal instance is not callable")."""
    opened = []
    monkeypatch.setattr(PronunciationDialog, "exec", lambda self: opened.append(self) or 0)
    open_book(window, PDF)
    _button(window.review_page, "Continue to voice and export").click()
    assert window.stack.currentIndex() == PRODUCE
    _button(window.produce_page, "Pronunciations…").click()
    assert len(opened) == 1
    _button(window.produce_page, "Back to review").click()
    assert window.stack.currentIndex() == REVIEW


def test_open_page_text_has_room(window):
    window.show()
    QApplication.processEvents()
    page = window.open_page
    status, title = page.status, page.findChildren(type(page.status))[0]
    assert status.width() >= 400
    assert status.height() >= status.heightForWidth(status.width())  # not squeezed
    assert title.geometry().bottom() <= status.geometry().top()  # no overlap
    window.hide()


def test_a_plan_made_before_a_change_is_not_kept(window):
    """Review finding 17: a pronunciation saved while the first plan was being made."""
    from pagevoice_gui.produce import _Planned

    open_book(window, PDF)
    page = window.produce_page
    plan = page._planner()
    planned = plan(lambda _msg: None)  # made with the settings of that moment
    page.plan_changed()  # e.g. a pronunciation was saved meanwhile
    page._keep_plan(planned)
    assert page.renderer is None  # the next render or export plans again
    page._keep_plan(_Planned(planned.renderer, page._generation))
    assert page.renderer is planned.renderer


def test_pronunciations_are_locked_while_work_runs(window):
    open_book(window, PDF)
    page = window.produce_page
    page.pause.set()
    page.start_render()
    page.pause.set()
    wait_until(lambda: page.renderer is not None)
    assert not page.pronunciations.isEnabled()
    assert not window.pronunciations_action.isEnabled()
    page.stop_work()
    wait_until(lambda: not page.busy)
    assert page.pronunciations.isEnabled() and window.pronunciations_action.isEnabled()


def test_existing_m4b_needs_a_yes(window, monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No
    )
    open_book(window, PDF)
    page = window.produce_page
    bought = tmp_path / "Dune.m4b"
    bought.write_bytes(b"bought")
    page.target.setText(str(bought))
    page.start_export()
    assert asked and "already exists" in asked[0]
    assert not page.busy and bought.read_bytes() == b"bought"
