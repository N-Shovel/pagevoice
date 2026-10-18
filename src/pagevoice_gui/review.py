"""The review screen (SPEC §4): the cleaned text with every removal shown dimmed, its
reason on hover, restorable with a click; flagged pages; chapter rename, merge and split.

Long chapters (an OCR'd scan can be one chapter) are shown in parts, and a restore click
restyles only the clicked text, so the screen stays quick on big books."""

import html
from collections import Counter

from PySide6.QtCore import QPoint, QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pagevoice.document import Chapter, Paragraph, Reason, Span
from pagevoice.edit import EditError, merge_with_next, rename_chapter, set_restored, split_at
from pagevoice_gui.session import Session

PART = 200  # paragraphs shown at once
DIM = "#8a8a8a"
RESTORED_BACKGROUND = QColor(80, 170, 80, 46)
REMOVED_STYLE = f"color:{DIM}; text-decoration:line-through;"
RESTORED_STYLE = "color:inherit; background-color:rgba(80,170,80,0.18); text-decoration:none;"


def read_notes_setting() -> bool:
    return QSettings().value("read_notes", True, type=bool)


class ReviewPage(QWidget):
    continue_clicked = Signal()
    clean_again_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.session: Session | None = None
        self._spans: dict[str, tuple[Span, int]] = {}  # ref -> (span, text block)
        self._blocks: list[int | None] = []  # text block -> body paragraph index
        self._words: dict[int, int] = {}  # id(chapter) -> words read
        self._removed: Counter = Counter()  # reason -> spans still removed
        self._restored = 0
        self._part = 0

        self.REASONS = {
            Reason.HEADER: self.tr("running header"),
            Reason.FOOTER: self.tr("running footer"),
            Reason.PAGE_NUMBER: self.tr("page number"),
            Reason.FOOTNOTE: self.tr("footnote"),
            Reason.FOOTNOTE_MARKER: self.tr("footnote marker"),
            Reason.CAPTION: self.tr("caption"),
            Reason.TABLE: self.tr("table"),
            Reason.CONTENTS: self.tr("table of contents"),
            Reason.BOILERPLATE: self.tr("licence or publisher boilerplate"),
            Reason.HYPHEN: self.tr("line-break hyphen"),
            Reason.MULTI_COLUMN: self.tr("page with more than one column (not read yet)"),
            Reason.NO_TEXT: self.tr("scanned page with no text"),
            Reason.FIGURE: self.tr("picture text"),
            Reason.NON_LINEAR: self.tr("extra outside the reading order"),
        }

        self.flags = QLabel(wordWrap=True)
        self.flags.setStyleSheet(
            "QLabel { background:#fff4ce; color:#3b2f00; padding:8px; border-radius:4px; }"
        )
        self.summary = QLabel(wordWrap=True)

        self.chapters = QListWidget()
        self.chapters.currentRowChanged.connect(self._chapter_selected)
        self.chapters.itemDoubleClicked.connect(lambda _item: self.rename())
        left = QVBoxLayout()
        left.addWidget(QLabel(self.tr("Chapters")))
        left.addWidget(self.chapters)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton(self.tr("Rename…"), clicked=lambda: self.rename()))
        buttons.addWidget(QPushButton(self.tr("Merge with next"), clicked=lambda: self.merge()))
        left.addLayout(buttons)
        left_box = QWidget()
        left_box.setLayout(left)

        self.text = QTextBrowser(openLinks=False)
        self.text.anchorClicked.connect(self._anchor_clicked)
        self.text.highlighted.connect(self._hovered)
        self.text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self._context_menu)
        self.previous_part = QPushButton(self.tr("◀ Previous part"), clicked=lambda: self._turn(-1))
        self.next_part = QPushButton(self.tr("Next part ▶"), clicked=lambda: self._turn(1))
        self.part_label = QLabel()
        parts = QHBoxLayout()
        parts.addWidget(self.previous_part)
        parts.addStretch()
        parts.addWidget(self.part_label)
        parts.addStretch()
        parts.addWidget(self.next_part)
        self.parts_bar = QWidget()
        self.parts_bar.setLayout(parts)
        self.hint = QLabel(wordWrap=True)
        self._default_hint()
        right = QVBoxLayout()
        right.addWidget(self.text)
        right.addWidget(self.parts_bar)
        right.addWidget(self.hint)
        right_box = QWidget()
        right_box.setLayout(right)

        splitter = QSplitter()
        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setStretchFactor(1, 3)

        clean_again = QPushButton(self.tr("Clean again from scratch…"), clicked=self._clean_again)
        go_on = QPushButton(self.tr("Continue to voice and export"))
        go_on.clicked.connect(lambda: self.continue_clicked.emit())  # a signal isn't a slot
        go_on.setDefault(True)
        bottom = QHBoxLayout()
        bottom.addWidget(clean_again)
        bottom.addStretch()
        bottom.addWidget(go_on)

        layout = QVBoxLayout(self)
        layout.addWidget(self.flags)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, 1)
        layout.addLayout(bottom)

    # --- showing the book ---

    def set_session(self, session: Session) -> None:
        self.session = session
        book = session.book
        self._words.clear()
        removals = book.removals
        self._removed = Counter(s.reason for s in removals if s.removed)
        self._restored = sum(1 for s in removals if s.restored)
        self._show_flags()
        self._refresh_chapters(0)

    def _show_flags(self) -> None:
        book = self.session.book
        if not book.flags:
            self.flags.hide()
            return
        pages = Counter(f.kind for f in book.flags)
        parts = []
        if pages["scanned"]:
            parts.append(self.tr(
                "%n page(s) are scans with no text, so PageVoice can't read them. Run the PDF "
                "through OCR first if you need them.", "", pages["scanned"]
            ))  # fmt: skip
        if pages["multi_column"]:
            parts.append(self.tr(
                "%n page(s) have more than one column. Their text is dimmed below because the "
                "reading order may be wrong; check it before restoring.", "", pages["multi_column"]
            ))  # fmt: skip
        listed = ", ".join(str(f.page) for f in book.flags[:20])
        more = "…" if len(book.flags) > 20 else ""
        self.flags.setText(" ".join(parts) + " " + self.tr("Pages: ") + listed + more)
        self.flags.show()

    def _refresh_summary(self) -> None:
        if self._removed:
            listed = ", ".join(
                f"{n} × {self.REASONS.get(r, str(r))}" for r, n in self._removed.most_common() if n
            )
            text = self.tr("Taken out of the reading: ") + listed + "."
        else:
            text = self.tr("Nothing was taken out of the reading.")
        if self._restored:
            text += " " + self.tr("%n brought back by you.", "", self._restored)
        self.summary.setText(text)

    def _chapter_text(self, number: int, chapter: Chapter) -> str:
        key = id(chapter)
        if key not in self._words:
            self._words[key] = sum(len(t.split()) for t in chapter.readable())
        return self.tr("%1. %2  (%3 words)").replace("%1", str(number)).replace(
            "%2", chapter.title).replace("%3", f"{self._words[key]:,}")  # fmt: skip

    def _refresh_chapters(self, select: int) -> None:
        """After a merge, split or rename: the list itself changes."""
        self.chapters.blockSignals(True)
        self.chapters.clear()
        for number, chapter in enumerate(self.session.book.chapters, 1):
            item = QListWidgetItem(self._chapter_text(number, chapter))
            item.setToolTip(chapter.title)
            self.chapters.addItem(item)
        self.chapters.blockSignals(False)
        self.chapters.setCurrentRow(max(0, min(select, self.chapters.count() - 1)))
        self._chapter_selected(self.chapters.currentRow())
        self._refresh_summary()

    def _chapter_selected(self, index: int) -> None:
        self._part = 0
        self._show_chapter(index)

    def _turn(self, step: int) -> None:
        self._part += step
        self._show_chapter(self.chapters.currentRow(), keep_scroll=False)

    def refresh(self) -> None:
        """Re-show the current chapter, e.g. after the notes setting changed."""
        if self.session:
            self._show_chapter(self.chapters.currentRow())

    def _show_chapter(self, index: int, keep_scroll: bool = True) -> None:
        self._spans.clear()
        self._blocks = []
        if index < 0 or not self.session:
            self.text.clear()
            self.parts_bar.hide()
            return
        chapter = self.session.book.chapters[index]
        parts_count = max(1, -(-len(chapter.paragraphs) // PART))
        self._part = max(0, min(self._part, parts_count - 1))
        first = self._part * PART
        pieces = []
        for p in range(first, min(first + PART, len(chapter.paragraphs))):
            pieces.append(self._paragraph_html(chapter.paragraphs[p], f"b{p}", len(self._blocks)))
            self._blocks.append(p)
        if chapter.notes and self._part == parts_count - 1:
            reading = read_notes_setting()
            heading = (
                self.tr("Notes, read at the end of the chapter:")
                if reading
                else self.tr("Notes, not read: footnotes are turned off in Voice and export.")
            )
            pieces.append(f"<p><i>{html.escape(heading)}</i></p>")
            self._blocks.append(None)
            for n, paragraph in enumerate(chapter.notes):
                block = self._paragraph_html(paragraph, f"n{n}", len(self._blocks))
                pieces.append(block if reading else f'<div style="color:{DIM}">{block}</div>')
                self._blocks.append(None)
        self.parts_bar.setVisible(parts_count > 1)
        self.part_label.setText(self.tr("Part %1 of %2").replace("%1", str(self._part + 1))
                                .replace("%2", str(parts_count)))  # fmt: skip
        self.previous_part.setEnabled(self._part > 0)
        self.next_part.setEnabled(self._part < parts_count - 1)
        position = self.text.verticalScrollBar().value() if keep_scroll else 0
        self.text.setHtml("".join(pieces))
        self.text.verticalScrollBar().setValue(position)

    def _paragraph_html(self, paragraph: Paragraph, key: str, block: int) -> str:
        pieces = []
        for s, span in enumerate(paragraph.spans):
            text = html.escape(span.text)
            if span.reason is None:
                pieces.append(text)
                continue
            ref = f"{key}s{s}"
            self._spans[ref] = (span, block)
            style = RESTORED_STYLE if span.restored else REMOVED_STYLE
            pieces.append(f'<a href="span:{ref}" style="{style}">{text}</a>')
        body = "".join(pieces).strip() or "&#8203;"
        if paragraph.kind == "heading":
            return f"<h3>{body}</h3>"
        return f"<p>{body}</p>"

    # --- edits ---

    def _anchor_clicked(self, url: QUrl) -> None:
        ref = url.toString().removeprefix("span:")
        if ref not in self._spans:
            return
        span, block = self._spans[ref]
        with self.session.lock:
            set_restored(span, not span.restored)
        self._removed[span.reason] += -1 if span.restored else 1
        self._restored += 1 if span.restored else -1
        self._restyle(f"span:{ref}", block, span.restored)
        index = self.chapters.currentRow()
        chapter = self.session.book.chapters[index]
        self._words.pop(id(chapter), None)
        self.chapters.item(index).setText(self._chapter_text(index + 1, chapter))
        self._refresh_summary()
        self._hovered(url)
        self.session.changed()

    def _restyle(self, href: str, block_number: int, restored: bool) -> None:
        """Restyle one removal in place: no re-layout of the whole chapter."""
        block = self.text.document().findBlockByNumber(block_number)
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.charFormat().anchorHref() == href:
                cursor = QTextCursor(self.text.document())
                cursor.setPosition(fragment.position())
                cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.KeepAnchor)
                style = QTextCharFormat(fragment.charFormat())
                style.setFontStrikeOut(not restored)
                if restored:
                    style.setForeground(self.palette().text())
                    style.setBackground(RESTORED_BACKGROUND)
                else:
                    style.setForeground(QColor(DIM))
                    style.setBackground(QBrush())
                cursor.setCharFormat(style)
            it += 1

    def _default_hint(self) -> None:
        self.hint.setText(self.tr(
            "Dimmed text won't be read. Click it to bring it back; click again to remove it. "
            "Right-click a paragraph to start a new chapter there."
        ))  # fmt: skip

    def _hovered(self, url: QUrl) -> None:
        found = self._spans.get(url.toString().removeprefix("span:"))
        if found is None:
            self._default_hint()
            return
        span = found[0]
        reason = self.REASONS.get(span.reason, str(span.reason))
        if span.location.page:
            reason = self.tr("%1 on page %2").replace("%1", reason).replace(
                "%2", str(span.location.page))  # fmt: skip
        if span.restored:
            text = self.tr("Removed as %1, brought back by you (click to remove again).")
        else:
            text = self.tr("Removed as %1 (click to bring it back).")
        self.hint.setText(text.replace("%1", reason))

    def _context_menu(self, pos: QPoint) -> None:
        block = self.text.cursorForPosition(pos).blockNumber()
        paragraph = self._blocks[block] if 0 <= block < len(self._blocks) else None
        menu = QMenu(self)
        action = menu.addAction(self.tr("Start a new chapter here"))
        action.setEnabled(bool(paragraph))  # not the first paragraph, not a note
        if menu.exec(self.text.mapToGlobal(pos)) is action and paragraph:
            self.split(paragraph)

    def split(self, paragraph: int, title: str | None = None) -> None:
        index = self.chapters.currentRow()
        chapter = self.session.book.chapters[index]
        known = chapter.paragraphs[paragraph].kind == "heading" or any(
            m.paragraph == paragraph for m in chapter.merged
        )
        if title is None and not known:
            title, ok = QInputDialog.getText(
                self, self.tr("New chapter"), self.tr("Title of the new chapter:"),
                text=self.tr("Chapter %1").replace("%1", str(index + 2)),
            )  # fmt: skip
            if not ok:
                return
        try:
            with self.session.lock:
                split_at(self.session.book, index, paragraph, title)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Split chapter"), str(exc))
            return
        self._words.pop(id(chapter), None)
        self._part = 0
        self._edited(index + 1)

    def rename(self, title: str | None = None) -> None:
        index = self.chapters.currentRow()
        if index < 0:
            return
        if title is None:
            current = self.session.book.chapters[index].title
            title, ok = QInputDialog.getText(
                self, self.tr("Rename chapter"), self.tr("Chapter title:"), text=current
            )
            if not ok:
                return
        try:
            with self.session.lock:
                rename_chapter(self.session.book, index, title)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Rename chapter"), str(exc))
            return
        self._edited(index)

    def merge(self) -> None:
        index = self.chapters.currentRow()
        # Forget both counts now: the merged-away chapter's id() can be reused later.
        for chapter in self.session.book.chapters[index : index + 2]:
            self._words.pop(id(chapter), None)
        try:
            with self.session.lock:
                merge_with_next(self.session.book, index)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Merge chapters"), str(exc))
            return
        self._edited(index)

    def _clean_again(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Clean again"),
            self.tr("Throw away your review changes for this book and clean it again from the "
                    "original file?"),
        )  # fmt: skip
        if answer == QMessageBox.Yes:
            self.clean_again_clicked.emit()

    def _edited(self, select: int) -> None:
        self._refresh_chapters(select)
        self.session.changed()
