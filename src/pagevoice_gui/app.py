"""Start the PageVoice desktop app.

pagevoice-gui [BOOK] [--dev-proposed-manifest]
"""

import argparse
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir
from PySide6.QtCore import QCoreApplication, qVersion
from PySide6.QtWidgets import QApplication, QMessageBox

from pagevoice import __version__

log = logging.getLogger("pagevoice_gui")


def log_file() -> Path:
    folder = Path(user_log_dir("PageVoice", appauthor=False))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "pagevoice.log"


def _setup_logging() -> None:
    handler = RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _excepthook(kind, value, tb) -> None:
    """Never show a traceback: log it, show a short message (.claude/rules/gui.md)."""
    log.error("Unexpected error:\n%s", "".join(traceback.format_exception(kind, value, tb)))
    if QApplication.instance():
        message = QCoreApplication.translate(
            "PageVoice", "Something went wrong: %1.\nDetails are in %2."
        )
        QMessageBox.warning(
            None,
            "PageVoice",
            message.replace("%1", str(value) or kind.__name__).replace("%2", str(log_file())),
        )


def make_window(dev_proposed_manifest: bool = False):
    from pagevoice.voice.engine import DEFAULT_VOICE, VoiceSetup
    from pagevoice.voice.kokoro import dml_available
    from pagevoice.voice.manifest import ManifestError, load_manifest
    from pagevoice_gui.main_window import MainWindow
    from pagevoice_gui.produce import VoiceUnavailable

    # Development only: the proposed manifest, and with it the upstream download source.
    # The installed app always uses the real manifest and our own release (D9).
    dev = dev_proposed_manifest and not getattr(sys, "frozen", False)
    try:
        manifest = load_manifest(allow_proposed=dev)
        voices = sorted(manifest.voices)
    except ManifestError:
        log.exception("No model manifest")
        manifest, voices = None, [DEFAULT_VOICE]

    def voice_factory(name: str, provider: str) -> VoiceSetup:
        if manifest is None:
            raise VoiceUnavailable(
                QCoreApplication.translate(
                    "PageVoice",
                    "This copy of PageVoice is missing its list of voice files, so it can't "
                    "set up the voice. Reinstall PageVoice.",
                )
            )
        return VoiceSetup(manifest, voice=name, provider=provider)

    return MainWindow(voice_factory, voices, dml=dml_available(), allow_upstream_download=dev)


def _icon_path() -> Path | None:
    """The window icon: in the packaged app's bundle, or in the source tree."""
    bundle = Path(getattr(sys, "_MEIPASS", "")) / "icons" / "pagevoice.png"
    source = Path(__file__).resolve().parents[2] / "packaging" / "icons" / "pagevoice.png"
    return next((p for p in (bundle, source) if p.is_file()), None)


def self_test(report: Path) -> int:
    """The engine's checks plus the GUI's own: Qt starts and the main window builds."""
    import os

    from pagevoice.selftest import write_report

    def qt() -> str:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no screen on a CI runner
        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = make_window()
        window.close()
        app.processEvents()
        return f"Qt {qVersion()}"

    return 0 if write_report(report, {"qt": qt}) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pagevoice-gui")
    parser.add_argument("book", nargs="?")
    parser.add_argument("--dev-proposed-manifest", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"PageVoice {__version__}")
    parser.add_argument("--self-test", metavar="REPORT", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.self_test:  # packaged builds: check every part loads, write a JSON report
        return self_test(Path(args.self_test))

    _setup_logging()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("PageVoice")
    app.setApplicationName("PageVoice")
    app.setApplicationVersion(__version__)
    if (icon := _icon_path()) is not None:
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon)))
    sys.excepthook = _excepthook
    window = make_window(args.dev_proposed_manifest)
    window.show()
    if args.book:
        window.load_book(Path(args.book))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
