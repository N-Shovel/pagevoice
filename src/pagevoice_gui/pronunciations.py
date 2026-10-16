"""Pronunciation lists (SPEC §5): the global list and this book's list, which wins. Each
entry has a "sounds like" respelling or phonemes, whole-word and case options, and a
preview button. Lists import and export as TSV, so a list can be shared across a series."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pagevoice.pronounce.lexicon import Entry, LexiconError, load, merge, save

COLUMNS = ("word", "sounds_like", "phonemes", "whole_word", "case_sensitive", "note")
FLAGS = {"whole_word", "case_sensitive"}
Preview = Callable[[str, list[Entry]], None]  # (text, entries) -> plays it


class EntryTable(QWidget):
    def __init__(self, entries: list[Entry], preview: Preview, others: Callable, parent=None):
        super().__init__(parent)
        self.preview, self.others = preview, others
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([
            self.tr("Word"), self.tr("Sounds like"), self.tr("Phonemes (optional)"),
            self.tr("Whole word"), self.tr("Case-sensitive"), self.tr("Note"),
        ])  # fmt: skip
        self.table.horizontalHeader().setStretchLastSection(True)
        for entry in entries:
            self.add(entry)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton(self.tr("Add"), clicked=lambda: self.add(Entry(""))))
        buttons.addWidget(QPushButton(self.tr("Remove"), clicked=self.remove))
        buttons.addWidget(QPushButton(self.tr("Preview"), clicked=self.play))
        buttons.addStretch()
        buttons.addWidget(QPushButton(self.tr("Import…"), clicked=self.import_file))
        buttons.addWidget(QPushButton(self.tr("Export…"), clicked=self.export_file))
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def add(self, entry: Entry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, name in enumerate(COLUMNS):
            value = getattr(entry, name)
            item = QTableWidgetItem()
            if name in FLAGS:
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setCheckState(Qt.Checked if value else Qt.Unchecked)
            else:
                item.setText(value)
            self.table.setItem(row, column, item)
        if not entry.word:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(self.table.item(row, 0))

    def remove(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def entry(self, row: int) -> Entry | None:
        values = {}
        for column, name in enumerate(COLUMNS):
            item = self.table.item(row, column)
            if name in FLAGS:
                values[name] = item.checkState() == Qt.Checked
            else:
                values[name] = (item.text() if item else "").strip()
        if not values["word"] and not values["sounds_like"] and not values["phonemes"]:
            return None  # an empty row is simply skipped
        return Entry(**values)

    def entries(self) -> list[Entry]:
        """The table's entries; LexiconError names the first bad row."""
        out = []
        for row in range(self.table.rowCount()):
            entry = self.entry(row)
            if entry is None:
                continue
            if not entry.word:
                raise LexiconError(
                    self.tr("Row %1: the word is empty.").replace("%1", str(row + 1))
                )
            if not entry.sounds_like and not entry.phonemes:
                raise LexiconError(
                    self.tr("Row %1: '%2' needs a 'sounds like' or phonemes.")
                    .replace("%1", str(row + 1)).replace("%2", entry.word)
                )  # fmt: skip
            out.append(entry)
        return out

    def play(self) -> None:
        row = self.table.currentRow()
        entry = self.entry(row) if row >= 0 else None
        if entry is None or not entry.word:
            QMessageBox.information(self, self.tr("Preview"), self.tr("Pick an entry first."))
            return
        self.preview(entry.word, merge(self.others(), [entry]))

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Import pronunciations"), "", self.tr("Pronunciation lists (*.tsv *.txt)")
        )
        if not path:
            return
        try:
            imported = load(Path(path))
        except LexiconError as exc:
            QMessageBox.warning(self, self.tr("Import pronunciations"), str(exc))
            return
        known = {e.key() for e in self._safe_entries()}
        kept = 0
        for entry in imported:
            if entry.key() in known:
                kept += 1
            else:
                self.add(entry)
        if kept:
            QMessageBox.information(self, self.tr("Import pronunciations"), self.tr(
                "%n word(s) were already in this list, so they were kept as they are. Remove "
                "them first to take the imported version.", "", kept
            ))  # fmt: skip

    def export_file(self) -> None:
        try:
            entries = self.entries()
        except LexiconError as exc:
            QMessageBox.warning(self, self.tr("Export pronunciations"), str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Export pronunciations"), "pronunciations.tsv",
            self.tr("Pronunciation lists (*.tsv)"),
        )  # fmt: skip
        if path:
            save(Path(path), entries)

    def _safe_entries(self) -> list[Entry]:
        try:
            return self.entries()
        except LexiconError:
            return []


class PronunciationDialog(QDialog):
    def __init__(
        self, book_path: Path | None, global_path: Path, preview: Preview, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Pronunciations"))
        self.resize(820, 480)
        self.paths: list[tuple[Path, EntryTable]] = []
        tabs = QTabWidget()
        self.global_table = self._table(global_path, preview, lambda: [])
        if book_path is not None:
            book_table = self._table(book_path, preview, lambda: self.global_table._safe_entries())
            tabs.addTab(book_table, self.tr("This book"))
        tabs.addTab(self.global_table, self.tr("All books"))
        help_text = QLabel(
            self.tr(
                "Write how a word sounds with ordinary spelling, e.g. Hermione → "
                "her-my-oh-nee. Capitals don't mark stress; for exact stress, use phonemes. "
                "This book's entries win over the list for all books."
            ),
            wordWrap=True,
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(help_text)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _table(self, path: Path, preview: Preview, others) -> EntryTable:
        try:
            entries = load(path) if path.exists() else []
        except LexiconError as exc:
            QMessageBox.warning(self, self.tr("Pronunciations"), f"{path.name}: {exc}")
            entries = []
        table = EntryTable(entries, preview, others)
        self.paths.append((path, table))
        return table

    def accept(self) -> None:
        try:
            lists = [(path, table.entries()) for path, table in self.paths]
        except LexiconError as exc:
            QMessageBox.warning(self, self.tr("Pronunciations"), str(exc))
            return
        for path, entries in lists:
            if entries or path.exists():
                save(path, entries)
        super().accept()
