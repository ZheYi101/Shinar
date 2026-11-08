"""Check wheel resources and launch QML from an isolated temporary install."""

from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_wheel_resources.py path/to/package.whl")
    wheel = Path(sys.argv[1]).resolve()
    source = Path(__file__).resolve().parents[1] / "src/shinar/desktop/qml"
    expected = {
        "shinar/desktop/qml/" + path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    }
    expected.add("shinar/local_speech/catalog.json")
    reader = source.parent / "reader"
    upstream = json.loads((reader / "foliate/UPSTREAM.json").read_text(encoding="utf-8"))
    for name, checksum in upstream["files"].items():
        if hashlib.sha256((reader / "foliate" / name).read_bytes()).hexdigest() != checksum:
            raise SystemExit(f"Changed pinned reader dependency: {name}")
    expected.update(
        "shinar/desktop/reader/" + path.relative_to(reader).as_posix()
        for path in reader.rglob("*") if path.is_file()
    )
    samples = source.parents[1] / "local_speech/benchmark_samples"
    expected.update(
        "shinar/local_speech/benchmark_samples/" + path.name
        for path in samples.glob("*") if path.is_file()
    )
    expected.update(
        "shinar/desktop/assets/" + path.name
        for path in (source.parent / "assets").glob("*")
        if path.is_file()
    )
    runtime_resources = source.parents[1] / "local_speech/runtime_resources"
    expected.update(
        "shinar/local_speech/runtime_resources/"
        + path.relative_to(runtime_resources).as_posix()
        for path in runtime_resources.rglob("*")
        if path.is_file()
    )
    expected.update(
        "shinar/desktop/translations/" + path.name
        for path in (source.parent / "translations").glob("*")
        if path.is_file()
    )
    with ZipFile(wheel) as archive, TemporaryDirectory(prefix="shinar-wheel-") as directory:
        python_modules = {
            "shinar/desktop/" + path.relative_to(source.parent).as_posix()
            for path in source.parent.rglob("*.py")
        }
        packaged_modules = {
            name for name in archive.namelist()
            if name.startswith("shinar/desktop/") and name.endswith(".py")
        }
        if packaged_modules != python_modules:
            raise SystemExit("Desktop Python module inventory differs from source: " +
                             ", ".join(sorted(packaged_modules ^ python_modules)))
        missing = expected.difference(archive.namelist())
        if missing:
            raise SystemExit("Missing resources: " + ", ".join(sorted(missing)))
        stale = [
            name
            for name in expected
            if hashlib.sha256(archive.read(name)).digest()
            != hashlib.sha256((source.parents[2] / name).read_bytes()).digest()
        ]
        if stale:
            raise SystemExit("Stale resources: " + ", ".join(sorted(stale)))
        obsolete = {
            name
            for name in archive.namelist()
            if name.startswith("shinar/desktop/qml/") and name.endswith(".qml")
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
            SHINAR_KIRIGAMI_MODE="off",
            SHINAR_DATA_DIR=directory,
        )
        code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import asyncio
from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from shinar.desktop import app as desktop
from shinar.application import LearningWorkbench
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider
from shinar.core import LanguageEnum, ProficiencyLevel
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.shell.window import DesktopWindowController
from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.installation import manifest, runtime_spec
from shinar.local_speech.model_profile import voices
from shinar.local_speech.samples import benchmark_audio
import shinar.desktop.shell.window as window_module
root = Path(sys.argv[1])
assert Path(desktop.__file__).is_relative_to(root)
assert Path(window_module.__file__).is_relative_to(root)
async def learning_probe():
    path = root / 'learning-probe.sqlite3'
    work = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(path))
    try:
        material = await work.load_material(title='Isolated wheel probe',
            content='Two friends meet at the station. They discuss the afternoon train.',
            source_language=LanguageEnum.ENGLISH, target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE, learner_level=ProficiencyLevel.B1,
            auto_prepare=False)
        assert material.read_through == 0
        work.set_reading_scope(len(material.content))
        await work.start_session()
        await work.send_message('Why do the friends meet at the station?')
        assert len(work.session.messages) == 3
        identity = work.session.id
    finally:
        await work.aclose()
    restored = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(path))
    try:
        assert restored.session.id == identity and len(restored.session.messages) == 3
        assert restored.session_material().read_through == len(material.content)
    finally:
        await restored.aclose()
asyncio.run(learning_probe())
catalog_ids = {package.id for package in load_catalog()}
assert 'sensevoice-int8-20240717' in catalog_ids
assert 'sensevoice-int8-20250909' not in catalog_ids
melo_onnx = next(package for package in load_catalog() if package.id == 'melo-zhen-onnx')
assert melo_onnx.available_languages == ['zh']
assert len(voices('melo-english-en')) == 5
assert voices('voicevox-japanese')[0]['style_id'] == 3
assert len(runtime_spec('rtc-cpu').fingerprint) == 64
assert manifest()['runtimes']['melo-cuda']['device'] == 'cuda'
for language in ('en', 'ja', 'zh'):
    with benchmark_audio(language) as sample:
        assert sample.is_file() and sample.stat().st_size > 1000
QtWebEngineQuick.initialize()
app = QGuiApplication([])
prefs = DesktopPreferences(QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat))
vm = LearningViewModel(LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(root / 'smoke.sqlite3')), 'Mock', preferences=prefs)
engine = desktop.create_engine(vm,
    window_settings=QSettings(str(root / 'window.ini'), QSettings.Format.IniFormat),
    initial_visible=False)
assert engine.rootObjects()
assert engine.reader_runtime.profile.isOffTheRecord()
assert not app.windowIcon().isNull()
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
engine.lifecycle.close()
engine.workspace.close()
engine.speech_library.close()
vm.close()
window.close()
print('Installed-wheel learning/restart, QML, WindowController and frameless controls smoke passed')
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
