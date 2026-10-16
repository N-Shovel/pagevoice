"""Settings: the render cache's size cap, which the user can change (SPEC §8, D26)."""

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from pagevoice.render.cache import DEFAULT_CAP_BYTES, RenderCache
from pagevoice_gui.tasks import run_task

GB = 2**30


def cache_cap_bytes() -> int:
    """The user's cap from the settings (whole GB), or the default."""
    gb = QSettings().value("cache_cap_gb", DEFAULT_CAP_BYTES // GB, type=int)
    return max(1, gb) * GB


class SettingsDialog(QDialog):
    def __init__(self, cache: RenderCache, busy: bool, parent=None) -> None:
        super().__init__(parent)
        self.cache = cache
        self.setWindowTitle(self.tr("Settings"))
        self.cap = QSpinBox(minimum=1, maximum=500, suffix=" GB")
        self.cap.setValue(cache_cap_bytes() // GB)
        self.used = QLabel(self.tr("Measuring…"))
        self.empty = QPushButton(self.tr("Empty the cache…"), clicked=self._empty)
        self.empty.setEnabled(not busy)
        explain = QLabel(
            self.tr(
                "Rendered audio is kept so that a paused book carries on, and editing a few "
                "paragraphs re-renders only those. A 10-hour book takes 1–2 GB. When the cache "
                "is full, the audio used longest ago is removed first, never the current book's."
            ),
            wordWrap=True,
        )
        form = QFormLayout()
        form.addRow(self.tr("Render cache limit:"), self.cap)
        form.addRow(self.tr("In use now:"), self.used)
        form.addRow("", self.empty)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(explain)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._measure()

    def _measure(self) -> None:
        cache = self.cache

        def show(size: int) -> None:
            self.used.setText(self.tr("%1 GB").replace("%1", f"{size / GB:.2f}"))

        run_task(lambda _r: cache.size(), on_done=show)

    def _empty(self) -> None:
        answer = QMessageBox.question(
            self,
            self.tr("Empty the cache"),
            self.tr("Delete all rendered audio? Books will render again from the start."),
        )
        if answer != QMessageBox.Yes:
            return
        cache = self.cache

        def empty(_report) -> None:
            cache.clear_all()

        self.empty.setEnabled(False)
        run_task(empty, on_done=lambda _r: self._measure())

    def accept(self) -> None:
        QSettings().setValue("cache_cap_gb", self.cap.value())
        self.cache.cap_bytes = self.cap.value() * GB
        super().accept()
