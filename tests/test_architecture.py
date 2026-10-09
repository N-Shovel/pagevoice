"""Rules about how the code is put together, checked on every test run."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "pagevoice"
QT_MODULES = {"PySide6", "PySide2", "PyQt5", "PyQt6", "shiboken6", "qtpy"}


def imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_engine_never_imports_qt():
    offenders = {
        str(path.relative_to(ROOT)): sorted(imported_top_level_modules(path) & QT_MODULES)
        for path in ENGINE.rglob("*.py")
        if imported_top_level_modules(path) & QT_MODULES
    }
    assert not offenders, f"The engine must not import Qt: {offenders}"


def test_engine_never_imports_the_gui():
    offenders = [
        str(path.relative_to(ROOT))
        for path in ENGINE.rglob("*.py")
        if "pagevoice_gui" in imported_top_level_modules(path)
    ]
    assert not offenders, f"The engine must not import the GUI package: {offenders}"
