"""Check wheel resources and launch QML from an isolated temporary install."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_wheel_resources.py path/to/package.whl")
    wheel = Path(sys.argv[1]).resolve()
    source = Path(__file__).resolve().parents[1] / "src/lingualoop/desktop/qml"
    expected = {
        "lingualoop/desktop/qml/" + path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    }
    expected.add("lingualoop/local_speech/catalog.json")
    expected.update(
        "lingualoop/desktop/translations/" + path.name
        for path in (source.parent / "translations").glob("*")
        if path.is_file()
    )
    with ZipFile(wheel) as archive, TemporaryDirectory(prefix="lingualoop-wheel-") as directory:
        missing = expected.difference(archive.namelist())
        if missing:
            raise SystemExit("Missing resources: " + ", ".join(sorted(missing)))
        obsolete = {
            name
            for name in archive.namelist()
            if name.startswith("lingualoop/desktop/qml/") and name.endswith(".qml")
        }.difference(expected)
        if obsolete:
            raise SystemExit(
                "Obsolete QML resources (clean build/lib first): " + ", ".join(sorted(obsolete))
            )
        archive.extractall(directory)
        environment = dict(
            os.environ,
            QT_QPA_PLATFORM="offscreen",
            QT_QUICK_BACKEND="software",
            LINGUALOOP_KIRIGAMI_MODE="off",
            LINGUALOOP_DATA_DIR=directory,
        )
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from lingualoop.desktop import app as desktop
from lingualoop.application import LearningWorkbench
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider
from lingualoop.desktop.preferences import DesktopPreferences
from lingualoop.desktop.viewmodel import LearningViewModel
from lingualoop.desktop.window import DesktopWindowController
from lingualoop.local_speech.catalog import load_catalog
import lingualoop.desktop.window as window_module
root = Path(sys.argv[1])
assert Path(desktop.__file__).is_relative_to(root)
assert Path(window_module.__file__).is_relative_to(root)
assert any(package.id == 'sensevoice-int8-20250909' for package in load_catalog())
app = QGuiApplication([])
prefs = DesktopPreferences(QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
vm = LearningViewModel(LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(root / 'smoke.sqlite3')), 'Mock', preferences=prefs)
engine = desktop.create_engine(vm,
    window_settings=QSettings(str(root / 'window.ini'), QSettings.Format.IniFormat),
    initial_visible=False)
assert engine.rootObjects()
app.processEvents()
window = engine.rootObjects()[0]
assert not window.isVisible()
assert window.flags() & Qt.WindowType.FramelessWindowHint
assert isinstance(engine.window_controller, DesktopWindowController)
objects = {}
pending = [window.contentItem()]
while pending:
    item = pending.pop()
    objects[item.objectName()] = item
    pending.extend(item.childItems())
for name in ('windowMinimizeButton', 'windowMaximizeButton', 'windowCloseButton',
             'windowDragArea', 'resize_topLeft', 'resize_bottomRight'):
    assert name in objects, name
vm.close()
window.close()
print('Installed-wheel QML, WindowController and frameless controls smoke passed')
"""
        subprocess.run(
            [sys.executable, "-I", "-c", code, directory],
            cwd=directory,
            env=environment,
            check=True,
            timeout=30,
        )
        print(f"Verified {len(expected)} QML/icon/license resources in {wheel.name}")


if __name__ == "__main__":
    main()
