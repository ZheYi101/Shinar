"""Real QML clicks/layout; tiny synthetic download and numeric benchmark fixtures."""

import hashlib
import os
from pathlib import Path

import httpx


from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.local_speech.catalog import Artifact, load_catalog
from shinar.local_speech import RUNTIME_VERSION
from shinar.local_speech.downloads import ModelStore
from shinar.local_speech.storage import atomic_json
from shinar.providers import MockLearningLLMProvider
from tests.support.audio import FakeAudio
from tests.support.qt import click, until


from contextlib import contextmanager
from tests.support.patches import Patches


class SyntheticModelStore(ModelStore):
    def install(self, model, **kwargs):
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"model"))
        ) as client:
            return super().install(model, client=client, **kwargs)


@contextmanager
def speech_library_scene(tmp_path, *, navigate=True):
    with Patches() as changes:
        yield from _speech_library_scene(tmp_path, changes, navigate=navigate)


def _speech_library_scene(tmp_path, monkeypatch, *, navigate=True):
    import shinar.desktop.speech_library.work as module

    app = QGuiApplication.instance() or QGuiApplication(["speech-library-test"])
    if os.name == "nt":
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/msyh.ttc"))
    hardware = {
        "platform": "Windows",
        "architecture": "AMD64",
        "cpu": "测试 CPU",
        "logical_cpus": 8,
        "available_ram_bytes": 12 * 1024**3,
        "disk_free_bytes": 20 * 1024**3,
        "gpus": [],
    }
    monkeypatch.setattr(module, "detect_hardware", lambda _: hardware)
    monkeypatch.setattr(
        "shinar.desktop.speech_library.work.prepare_managed_runtime",
        lambda *args, **kwargs: {"prepared": True},
    )
    monkeypatch.setattr(module, "runtime_status", lambda *args, **kwargs: {"prepared": True})
    library = SpeechLibraryViewModel(tmp_path / "speech", store_factory=SyntheticModelStore)
    artifact = Artifact(
        path="model.onnx",
        url="https://models.example/test",
        size=5,
        sha256=hashlib.sha256(b"model").hexdigest(),
    )
    package = next(p for p in load_catalog() if p.id == "kokoro-int8-zhen-v11").model_copy(
        update={
            "id": "test-tts",
            "revision": "test",
            "files": [artifact],
            "required_files": ["model.onnx"],
        }
    )
    library.configure_catalog([package])

    def benchmark(store, packages, language, **_):
        atomic_json(
            store.root / "reports/test.json",
            {
                "schema": 1,
                "hardware": hardware,
                "language": language,
                "model_fingerprints": {package.id: package.fingerprint},
                "repeats": 5,
                "metrics": {
                    "runtime_version": RUNTIME_VERSION,
                    "provider": "cpu",
                    "threads_per_model": 2,
                    "sequential": {"tts": [{"first_pcm_ms": 150}]},
                },
            },
        )

    monkeypatch.setattr("shinar.desktop.speech_library.work.benchmark", benchmark)
    workbench = LearningWorkbench(
        MockLearningLLMProvider(), event_store=SQLiteStore(tmp_path / "app.sqlite3")
    )
    prefs = DesktopPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
    vm = LearningViewModel(workbench, "Mock 调试", preferences=prefs, audio_controller=FakeAudio())
    engine = create_engine(
        vm,
        window_settings=QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat),
        speech_library=library,
    )
    window = engine.rootObjects()[0]
    window.setWidth(800)
    window.setHeight(900)
    scaffold = next(
        obj
        for obj in window.findChildren(QObject)
        if obj.metaObject().indexOfProperty("currentPage") >= 0
    )
    scaffold.setProperty("currentPage", 3)
    QTest.qWait(100)
    if navigate:
        click(window, "settings-local")
    else:
        engine.workspace.setCategory("local")
        engine.workspace.navigate("settings")
    until(
        lambda: any(
            obj.property("visible")
            for obj in window.findChildren(QObject)
            if obj.objectName() == "speechModelsPage"
        )
    )
    QTest.qWait(300)
    until(lambda: not library.busy)
    try:
        yield app, library, vm, window, engine, tmp_path
    finally:
        engine.lifecycle.close()
        engine.ai_services.close()
        engine.workspace.close()
        library.close()
        vm.close()
        window.close()
        engine.deleteLater()
        app.processEvents()
