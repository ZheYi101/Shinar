"""Real QML clicks/layout; tiny synthetic download and numeric benchmark fixtures."""

import hashlib
import os
from pathlib import Path

import httpx
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtTest import QSignalSpy

from lingualoop.application import LearningWorkbench
from lingualoop.desktop.app import create_engine
from lingualoop.desktop.preferences import DesktopPreferences
from lingualoop.desktop.speech_library import SpeechLibraryViewModel
from lingualoop.desktop.viewmodel import LearningViewModel
from lingualoop.infrastructure import SQLiteStore
from lingualoop.local_speech.catalog import Artifact, load_catalog
from lingualoop.local_speech import RUNTIME_VERSION
from lingualoop.local_speech.storage import atomic_json, read_json
from lingualoop.providers import MockLearningLLMProvider
from test_desktop_workflow import FakeAudio, click, item, until


@pytest.fixture
def library_desktop(tmp_path, monkeypatch):
    import lingualoop.desktop.speech_library as module

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
    library = SpeechLibraryViewModel(tmp_path / "speech")
    artifact = Artifact(
        path="model.onnx",
        url="https://models.example/test",
        size=5,
        sha256=hashlib.sha256(b"model").hexdigest(),
    )
    package = load_catalog()[2].model_copy(
        update={
            "id": "test-tts",
            "revision": "test",
            "files": [artifact],
            "required_files": ["model.onnx"],
        }
    )
    library.catalog = [package]
    original = library.store.install

    def install(model, **kwargs):
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"model"))
        ) as transport:
            return original(model, client=transport, **kwargs)

    monkeypatch.setattr(library.store, "install", install)

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

    monkeypatch.setattr(module, "benchmark", benchmark)
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
    # Opening uses the actual button; bring its enclosing ScrollView into view.
    target = item(window, "openLocalSpeechLibrary")
    parent = target.parentItem()
    while parent and parent.metaObject().indexOfProperty("contentY") < 0:
        parent = parent.parentItem()
    assert parent is not None
    parent.setProperty("contentY", parent.property("contentHeight") - parent.height())
    QTest.qWait(100)
    click(window, "openLocalSpeechLibrary")
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
        library.close()
        vm.close()
        window.close()
        engine.deleteLater()
        app.processEvents()


def test_library_download_benchmark_select_and_restart(library_desktop):
    app, library, vm, window, engine, root = library_desktop
    library.setFilter("en", "conversation")
    until(lambda: not library.busy)
    QTest.qWait(100)
    click(window, "speechInstall-test-tts", scroll="speechModelsPage")
    until(lambda: not library.busy)
    assert library.models[0]["installed"]
    click(window, "speechBenchmark-test-tts", scroll="speechModelsPage")
    until(lambda: not library.busy)
    assert library.models[0]["measured"]
    click(window, "speechSelect-test-tts", scroll="speechModelsPage")
    assert read_json(root / "speech/selections.json")["en:conversation:tts"]["id"] == "test-tts"
    restored = SpeechLibraryViewModel(root / "speech")
    restored.catalog = library.catalog
    restored.setFilter("en", "conversation")
    until(lambda: not restored.busy)
    assert restored.models[0]["installed"] and restored.models[0]["measured"]
    restored.close()


def test_progress_does_not_recreate_model_cards(library_desktop):
    app, library, vm, window, engine, root = library_desktop
    models = QSignalSpy(library.modelsChanged)
    progress = QSignalSpy(library.progressChanged)

    def wait_for_cancel():
        library._cancel.wait(2)
        return library._snapshot()

    library._start("测试进度更新", wait_for_cancel)
    QTest.qWait(400)
    assert library.busy and models.count() == 0
    assert progress.count() >= 2
    click(window, "speechCancel", scroll="speechModelsPage")
    until(lambda: not library.busy)


@pytest.mark.parametrize("theme,width", [("light", 360), ("dark", 360), ("light", 1440), ("dark", 800)])
def test_compute_subpage_device_budget_and_idle_settings(library_desktop, monkeypatch, theme, width):
    from PySide6.QtCore import Qt
    import lingualoop.desktop.speech_library as module
    app, library, vm, window, engine, root = library_desktop
    monkeypatch.setattr(module, "resource_snapshot", lambda *args: {
        "gpus": [{"index": 0, "name": "测试 GPU", "used_mb": 2345, "total_mb": 8192, "utilization": 37}],
        "speech_process_mb": None, "process_count": 1,
    })
    vm.preferences.setValue("themeMode", theme)
    window.setWidth(width)
    click(window, "speechSettingsBack")
    click(window, "openSpeechCompute", scroll="settingsOverview")
    until(lambda: not library.busy)
    until(lambda: "2345" in library.resourceSummary)
    page = item(window, "speechComputePage")
    assert page.isVisible() and page.property("contentWidth") <= page.width() + 1
    device = item(window, "compute-stt_device")
    device.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Down)
    until(lambda: library.compute["stt_device"] == "cpu" and not library.busy)
    # A reload must retain the user's CPU choice, rather than re-selecting GPU.
    assert read_json(root / "speech/compute.json", {})["stt_device"] == "cpu"
    assert "整卡使用率 37%" in library.resourceSummary
    assert "驱动未提供进程级读数" in library.resourceSummary
    click(window, "speechReleaseModels", scroll="speechComputePage")
    assert "释放" in library.status


def test_local_route_uses_conversation_language_and_does_not_call_remote(library_desktop):
    import asyncio
    app, library, vm, window, engine, root = library_desktop
    from lingualoop.local_speech.compute import ComputeSettings, save_compute
    save_compute(library.store.root, ComputeSettings(local_stt=True))
    vm.preferences.setValue("targetLanguage", "japanese")
    library._language = "en"
    calls = []
    async def transcribe(audio, language):
        calls.append((audio, language))
        return "テスト"
    library.local_service.transcribe = transcribe
    assert asyncio.run(vm._speech_operation("stt", b"audio")()) == "テスト"
    assert calls == [(b"audio", "ja")]


@pytest.mark.parametrize("width", [360, 600, 800, 1180, 1440])
def test_library_responsive_geometry(library_desktop, width):
    app, library, vm, window, engine, root = library_desktop
    window.setWidth(width)
    library.setFilter("en", "conversation")
    until(lambda: not library.busy)
    QTest.qWait(100)
    language = item(window, "speechLanguage")
    assert language.width() >= 100
    scroll = item(window, "speechModelsPage")
    assert scroll.property("contentWidth") <= scroll.width() + 1
    install = item(window, "speechInstall-test-tts")
    assert install.width() <= scroll.width()
    # Dialog keeps every action scrollable at narrow sizes.
    click(window, "speechRefresh", scroll="speechModelsPage")
    until(lambda: not library.busy)
