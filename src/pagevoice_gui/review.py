"""The review screen (SPEC §4): the cleaned text with every removal shown dimmed, its
reason on hover, restorable with a click; flagged pages; chapter rename, merge and split."""

import html
from collections import Counter

from PySide6.QtCore import QPoint, Qt, QUrl, Signal
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

from pagevoice.document import Paragraph, Reason, Span
from pagevoice.edit import EditError, merge_with_next, rename_chapter, set_restored, split_at
from pagevoice_gui.session import Session

REMOVED_STYLE = "color:#8a8a8a; text-decoration:line-through;"
RESTORED_STYLE = "color:inherit; background-color:rgba(80,170,80,0.18); text-decoration:none;"
LINK_STYLE = "color:inherit; text-decoration:none;"


class ReviewPage(QWidget):
    continue_clicked = Signal()
    clean_again_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.session: Session | None = None
        self._spans: dict[str, Span] = {}
        self._blocks: list[int | None] = []  # text block -> body paragraph index

        self.REASONS = {
            Reason.HEADER: self.tr("running header"),
            Reason.FOOTER: self.tr("running footer"),
            Reason.PAGE_NUMBER: self.tr("page number"),
            Reason.FOOTNOTE: self.tr("footnote (notes are set to be dropped)"),
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
        self.chapters.currentRowChanged.connect(self._show_chapter)
        self.chapters.itemDoubleClicked.connect(lambda _item: self.rename())
        rename = QPushButton(self.tr("Rename…"), clicked=lambda: self.rename())
        merge = QPushButton(self.tr("Merge with next"), clicked=self.merge)
        left = QVBoxLayout()
        left.addWidget(QLabel(self.tr("Chapters")))
        left.addWidget(self.chapters)
        buttons = QHBoxLayout()
        buttons.addWidget(rename)
        buttons.addWidget(merge)
        left.addLayout(buttons)
        left_box = QWidget()
        left_box.setLayout(left)

        self.text = QTextBrowser(openLinks=False)
        self.text.anchorClicked.connect(self._anchor_clicked)
        self.text.highlighted.connect(self._hovered)
        self.text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self._context_menu)
        self.hint = QLabel(
            self.tr(
                "Dimmed text won't be read. Click it to bring it back; click again to remove "
                "it. Right-click a paragraph to start a new chapter there."
            ),
            wordWrap=True,
        )
        right = QVBoxLayout()
        right.addWidget(self.text)
        right.addWidget(self.hint)
        right_box = QWidget()
        right_box.setLayout(right)

        splitter = QSplitter()
        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setStretchFactor(1, 3)

        clean_again = QPushButton(self.tr("Clean again from scratch…"), clicked=self._clean_again)
        go_on = QPushButton(self.tr("Continue to voice and export"), clicked=self.continue_clicked)
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
        if book.flags:
            pages = Counter(f.kind for f in book.flags)
            parts = []
            if pages["scanned"]:
                parts.append(
                    self.tr(
                        "%n page(s) are scans with no text, so PageVoice can't read them. "
                        "Run the PDF through OCR first if you need them.",
                        "",
                        pages["scanned"],
                    )
                )
            if pages["multi_column"]:
                parts.append(
                    self.tr(
                        "%n page(s) have more than one column. Their text is dimmed below "
                        "because the reading order may be wrong; check it before restoring.",
                        "",
                        pages["multi_column"],
                    )
                )
            listed = ", ".join(str(f.page) for f in book.flags[:20])
            more = "…" if len(book.flags) > 20 else ""
            self.flags.setText(" ".join(parts) + " " + self.tr("Pages: ") + listed + more)
            self.flags.show()
        else:
            self.flags.hide()
        self._refresh_chapters(0)

    def _refresh_summary(self) -> None:
        removals = self.session.book.removals
        counts = Counter(s.reason for s in removals if s.removed)
        restored = sum(1 for s in removals if s.restored)
        if counts:
            listed = ", ".join(f"{n} × {self.REASONS[r]}" for r, n in counts.most_common())
            text = self.tr("Taken out of the reading: ") + listed + "."
        else:
            text = self.tr("Nothing was taken out of the reading.")
        if restored:
            text += " " + self.tr("%n brought back by you.", "", restored)
        self.summary.setText(text)

    def _refresh_chapters(self, select: int) -> None:
        self.chapters.blockSignals(True)
        self.chapters.clear()
        for number, chapter in enumerate(self.session.book.chapters, 1):
            words = sum(len(t.split()) for t in chapter.readable())
            item = QListWidgetItem(f"{number}. {chapter.title}  ({words:,} words)")
            item.setToolTip(chapter.title)
            self.chapters.addItem(item)
        self.chapters.blockSignals(False)
        self.chapters.setCurrentRow(min(select, self.chapters.count() - 1))
        self._show_chapter(self.chapters.currentRow())
        self._refresh_summary()

    def _show_chapter(self, index: int) -> None:
        self._spans.clear()
        self._blocks = []
        if index < 0 or not self.session:
            self.text.clear()
            return
        chapter = self.session.book.chapters[index]
        parts = []
        for p, paragraph in enumerate(chapter.paragraphs):
            parts.append(self._paragraph_html(paragraph, f"b{p}"))
            self._blocks.append(p)
        if chapter.notes:
            parts.append(f"<p><i>{html.escape(self.tr('Notes, read at the chapter end:'))}</i></p>")
            self._blocks.append(None)
            for n, paragraph in enumerate(chapter.notes):
                parts.append(self._paragraph_html(paragraph, f"n{n}"))
                self._blocks.append(None)
        position = self.text.verticalScrollBar().value()
        self.text.setHtml("".join(parts))
        self.text.verticalScrollBar().setValue(position)

    def _paragraph_html(self, paragraph: Paragraph, key: str) -> str:
        pieces = []
        for s, span in enumerate(paragraph.spans):
            text = html.escape(span.text)
            if span.reason is None:
                pieces.append(text)
                continue
            ref = f"{key}s{s}"
            self._spans[ref] = span
            style = RESTORED_STYLE if span.restored else REMOVED_STYLE
            pieces.append(f'<a href="span:{ref}" style="{style}">{text}</a>')
        body = "".join(pieces).strip() or "&#8203;"
        if paragraph.kind == "heading":
            return f"<h3>{body}</h3>"
        return f"<p>{body}</p>"

    # --- edits ---

    def _anchor_clicked(self, url: QUrl) -> None:
        span = self._spans.get(url.toString().removeprefix("span:"))
        if span is None:
            return
        set_restored(span, not span.restored)
        self._edited(self.chapters.currentRow())

    def _hovered(self, url: QUrl) -> None:
        span = self._spans.get(url.toString().removeprefix("span:"))
        if span is None:
            self.hint.setText(self.tr("Click dimmed text to bring it back."))
            return
        where = self.tr(" on page %1").replace("%1", str(span.location.page))
        reason = self.REASONS.get(span.reason, str(span.reason))
        state = self.tr("brought back; click to remove again") if span.restored else ""
        state = state or self.tr("click to bring it back")
        page = where if span.location.page else ""
        self.hint.setText(self.tr("Removed as %1%2 (%3).").replace("%1", reason)
                          .replace("%2", page).replace("%3", state))  # fmt: skip

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
        try:
            split_at(self.session.book, index, paragraph, title)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Split chapter"), str(exc))
            return
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
            rename_chapter(self.session.book, index, title)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Rename chapter"), str(exc))
            return
        self._edited(index)

    def merge(self) -> None:
        index = self.chapters.currentRow()
        try:
            merge_with_next(self.session.book, index)
        except EditError as exc:
            QMessageBox.information(self, self.tr("Merge chapters"), str(exc))
            return
        self._edited(index)

    def _clean_again(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Clean again"),
            self.tr(
                "Throw away your review changes for this book and clean it again from the "
                "original file?"
            ),
        )
        if answer == QMessageBox.Yes:
            self.clean_again_clicked.emit()

    def _edited(self, select: int) -> None:
        self._refresh_chapters(select)
        self.session.changed()
