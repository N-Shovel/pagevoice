# PyInstaller recipe for PageVoice (SPEC §9): ONE-FOLDER mode only, never one-file
# (antivirus tools flag one-file builds constantly; .claude/rules/packaging.md).
#
#   uv sync --locked --extra gui --group build
#   uv run pyinstaller packaging/pagevoice.spec --noconfirm
#
# Result: dist/PageVoice/ with PageVoice(.exe) and an _internal/ folder.
# The voice model is NOT bundled: it's downloaded on first run and checked against
# model_manifest.json (SPEC §2). ffmpeg comes from packaging/ffmpeg/out/<os>/ (built by
# packaging/ffmpeg/build.sh in CI); the build stops if it's missing.
# Check a build with:  dist/PageVoice/PageVoice --self-test report.json

import runpy
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is set by PyInstaller
OS = "windows" if sys.platform == "win32" else "linux"
FFMPEG_EXE = "ffmpeg.exe" if OS == "windows" else "ffmpeg"
FFMPEG = ROOT / "packaging" / "ffmpeg" / "out" / OS
if not (FFMPEG / "bin" / FFMPEG_EXE).is_file():
    raise SystemExit(f"Bundled ffmpeg missing: run packaging/ffmpeg/build.sh first ({FFMPEG})")

datas, binaries, hiddenimports = [], [], []

# Packages that need their data files, libraries or lazily imported modules collected.
for package in ("misaki", "espeakng_loader", "en_core_web_sm", "spacy", "thinc", "num2words",
                "phonemizer", "pdfminer", "pypdfium2", "pypdfium2_raw", "onnxruntime",
                "_soundfile_data", "_sounddevice_data", "language_tags", "segments", "csvw"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("pagevoice")  # the model manifest(s)

# ffmpeg and its licences: find_ffmpeg() looks in <bundle>/ffmpeg/ (D18).
binaries += [(str(FFMPEG / "bin" / FFMPEG_EXE), "ffmpeg")]
datas += [(str(p), "licenses/ffmpeg") for p in (FFMPEG / "licenses").glob("*") if p.is_file()]
datas += [(str(ROOT / "LICENSE"), ".")]
# Every bundled package's licence text, written fresh for this build.
_notices = ROOT / "build" / "THIRD_PARTY_LICENSES.txt"
runpy.run_path(str(ROOT / "tools" / "third_party.py"))["main"](str(_notices))
datas += [(str(_notices), ".")]
datas += [(str(ROOT / "packaging" / "icons" / "pagevoice.png"), "icons")]  # the window icon


def _keep(entry) -> bool:
    """PortAudio's ASIO builds are under Steinberg's own licence: never shipped (D36).
    Other platforms' and 32-bit PortAudio builds aren't needed either."""
    name = Path(entry[0]).name.lower()
    if "asio" in name:
        return False
    if name.startswith("libportaudio") and ("32bit" in name or "arm64" in name or name.endswith(".dylib")):
        return False
    return True


# Qt parts PageVoice never uses (it needs QtCore, QtGui and QtWidgets only).
QT_UNUSED = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtOpenGL", "PySide6.QtPdf",
    "PySide6.QtSvg", "PySide6.QtDBus", "PySide6.QtConcurrent", "PySide6.QtHelp",
    "PySide6.QtPrintSupport", "PySide6.QtDesigner", "PySide6.QtUiTools",
]  # fmt: skip
# Never bundled: test and development tools, and the banned PyTorch (D3).
EXCLUDES = QT_UNUSED + ["torch", "tkinter", "pytest", "faster_whisper", "mutagen",
                        "reportlab", "pip_licenses", "IPython", "matplotlib"]  # fmt: skip

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["pagevoice_gui.app"],
    excludes=EXCLUDES,
    noarchive=False,
)
a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # one-folder: libraries sit next to the exe
    name="PageVoice",
    console=False,  # a window app; --self-test writes its report to a file
    icon=str(ROOT / "packaging" / "icons" / "pagevoice.ico") if OS == "windows" else None,
    upx=False,  # compressed exes trip antivirus tools
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PageVoice",
)
