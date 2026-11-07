"""Real QML clicks/layout; tiny synthetic download and numeric benchmark fixtures."""

import hashlib
import os
from pathlib import Path
from threading import get_ident, Event

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
    monkeypatch.setattr("lingualoop.desktop.speech_library_operations.prepare_managed_runtime", lambda *args, **kwargs: {"prepared": True})
    monkeypatch.setattr(module, "runtime_status", lambda *args, **kwargs: {"prepared": True})
    library = SpeechLibraryViewModel(tmp_path / "speech")
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

    monkeypatch.setattr("lingualoop.desktop.speech_library_operations.benchmark", benchmark)
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
    click(window, "settings-local")
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
    assert library.models[0]["selected"]
    assert not item(window, "speechSelect-test-tts").isEnabled()
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
    click(window, "speechCancel")
    until(lambda: not library.busy)


@pytest.mark.parametrize("failure", [None, "slow", "cancelled"])
def test_default_stt_demo_benchmarks_and_selects_same_service_without_file_picker(
    library_desktop, monkeypatch, failure
):
    import asyncio
    import sys
    from types import SimpleNamespace
    import lingualoop.desktop.speech_library as module
    import lingualoop.local_speech.service as service_module
    import lingualoop.local_speech.model_profile as profiles
    from lingualoop.local_speech.downloads import DownloadCancelled
    from lingualoop.local_speech.samples import benchmark_audio

    _, library, vm, window, _, root = library_desktop
    package = next(p for p in load_catalog() if p.id == "sensevoice-int8-20240717")
    library.catalog = [package]
    monkeypatch.setattr(library.store, "installed", lambda _: True)
    monkeypatch.setattr(library.local_service.store, "installed", lambda _: True)
    monkeypatch.setattr(service_module, "detect_hardware", module.detect_hardware)
    monkeypatch.setattr(service_module, "runtime_status", lambda *a, **k: {"prepared": True})
    monkeypatch.setattr(service_module, "runtime_python", lambda *a: sys.executable)
    monkeypatch.setattr(profiles, "build_profile", lambda store, p, lang, device, **k:
                        SimpleNamespace(package_id=p.id, task=p.task, language=lang))
    observed = []

    def benchmark(store, packages, language, **kwargs):
        with benchmark_audio(language) as expected:
            assert Path(kwargs["wav"]).read_bytes() == expected.read_bytes()
        observed.append((packages[0].id, language))
        if failure == "cancelled":
            raise DownloadCancelled("测速已取消。")
        atomic_json(store.root / "reports/demo.json", {
            "schema": 1, "language": language, "hardware": module.detect_hardware(store.root),
            "model_fingerprints": {package.id: package.fingerprint}, "repeats": 5,
            "metrics": {"runtime_version": RUNTIME_VERSION, "provider": "cpu",
                        "threads_per_model": 2, "sequential": {"stt": [
                            {"compute_ms": 900 if failure == "slow" else 150,
                             "finalization_compute_ms": 900 if failure == "slow" else 150,
                             "nonempty": True}
                        ]}},
        })

    monkeypatch.setattr("lingualoop.desktop.speech_library_operations.benchmark", benchmark)
    library.setFilter("en", "conversation")
    until(lambda: not library.busy)
    click(window, "speechBenchmark-" + package.id, scroll="speechModelsPage")
    until(lambda: bool(observed) and not library.busy)
    dialog = window.findChild(QObject, "speechBenchmarkFile")
    assert not dialog.property("visible")
    assert observed == [(package.id, "en")]
    selected = read_json(root / "speech/selections.json", {})
    if failure:
        assert "en:conversation:stt" not in selected
        assert not library.models[0]["selected"]
        assert "500 ms" in library.status if failure == "slow" else "取消" in library.status
    else:
        assert selected["en:conversation:stt"]["id"] == package.id
        assert library.models[0]["selected"]
        assert library.local_service is vm._local_speech
        assert library.local_service.enabled("stt")
        bound = asyncio.run(vm._local_speech.resolve("stt", "en"))
        assert (bound.package_id, bound.language) == (package.id, "en")
        # A page filter never changes what an actual English conversation resolves.
        library.setFilter("ja", "reading")
        until(lambda: not library.busy)
        assert asyncio.run(vm._local_speech.resolve("stt", "en")).package_id == package.id


def test_preview_cannot_echo_into_active_voice_or_fall_back_from_a_removed_device(library_desktop, monkeypatch):
    from types import SimpleNamespace
    import lingualoop.desktop.speech_library as module

    _, library, _, _, _, root = library_desktop
    preview = library.store.root / "reports/fixture.wav"
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"synthetic fixture")
    library._rows = [{"id": "test-tts", "preview": str(preview)}]
    played = []
    library._player = SimpleNamespace(setSource=lambda value: played.append(value),
                                      play=lambda: played.append("play"), stop=lambda: None)
    library.configure_preview(lambda: "removed-device", lambda: True)
    library.preview("test-tts")
    assert "停止语音" in library.status and not played
    library.configure_preview(lambda: "removed-device", lambda: False)
    monkeypatch.setattr(module.QMediaDevices, "audioOutputs", lambda: [])
    library.preview("test-tts")
    assert "播放设备不可用" in library.status and not played


def test_voicevox_terms_and_style_are_explicit_and_do_not_replace_a_model_id(library_desktop):
    from PySide6.QtCore import Qt
    from lingualoop.local_speech.model_profile import accepted_terms, voice_choice
    app, library, vm, window, engine, root = library_desktop
    package = next(p for p in load_catalog() if p.id == "voicevox-japanese")
    library.catalog = [package]
    library.setFilter("ja", "conversation")
    until(lambda: not library.busy)
    assert not accepted_terms(library.store.root, package)
    click(window, "speechDetails-" + package.id, scroll="speechModelsPage")
    click(window, "speechTerms-" + package.id, scroll="speechModelsPage")
    until(lambda: not library.busy)
    assert accepted_terms(library.store.root, package)
    combo = item(window, "speechVoice-" + package.id)
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Down)
    until(lambda: not library.busy)
    assert voice_choice(library.store.root, package.id)["style_id"] == 1
    assert not read_json(root / "speech/selections.json", {})
    assert library.models[0]["id"] == "voicevox-japanese"


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
    click(window, "openSpeechCompute")
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
    from types import SimpleNamespace
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
    workbench = vm._workbench
    vm._workbench = SimpleNamespace(session=SimpleNamespace(profile=SimpleNamespace(target_language=SimpleNamespace(value="english"))))
    try:
        assert asyncio.run(vm._speech_operation("stt", b"session audio")()) == "テスト"
        assert calls[-1] == (b"session audio", "en")
    finally:
        vm._workbench = workbench


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
    click(window, "speechRefresh")
    until(lambda: not library.busy)


def test_inference_status_does_not_run_installation_checks_on_gui_thread(
    library_desktop, monkeypatch
):
    app, library, vm, window, engine, root = library_desktop
    click(window, "openSpeechCompute")
    until(lambda: not library.busy)
    gui_thread = get_ident()
    snapshots = []
    original = library._runtime_snapshot

    def snapshot():
        snapshots.append(get_ident())
        return original()

    monkeypatch.setattr(library, "_runtime_snapshot", snapshot)
    runtime_changes = QSignalSpy(library.runtimesChanged)
    for i in range(20):
        library.inferenceStatus.emit(f"TTS CPU {i}")
        app.processEvents()
        assert library.runtimes["cpu"]["prepared"]
    assert not snapshots and runtime_changes.count() == 0
    assert item(window, "computeStatus").property("text") == "TTS CPU 19"
    library.refresh()
    until(lambda: not library.busy)
    assert snapshots and all(thread != gui_thread for thread in snapshots)
    assert runtime_changes.count() == 1


def test_stt_and_tts_download_together_with_live_component_progress(library_desktop, monkeypatch):
    from lingualoop.local_speech.downloads import DownloadCancelled, TransferEvent
    app, library, vm, window, engine, root = library_desktop
    base = library.catalog[0]
    stt = base.model_copy(update={"id": "fixture-stt", "name": "Fixture STT", "task": "stt"})
    tts = base.model_copy(update={"id": "fixture-tts", "name": "Fixture TTS"})
    library.catalog = [stt, tts]
    library.setFilter("en", "conversation")
    until(lambda: not library.busy)
    gates = {stt.id: Event(), tts.id: Event()}
    original = library.store.install

    def install(package, **kwargs):
        transfer = kwargs["on_transfer"]
        transfer(TransferEvent(package.id + ".onnx", "downloading", 128, 1024))
        while not gates[package.id].wait(0.01):
            if kwargs["cancel"].is_set():
                raise DownloadCancelled()
        return original(package, **kwargs)

    monkeypatch.setattr(library.store, "install", install)
    try:
        click(window, "speechTabSTT")
        click(window, "speechInstall-" + stt.id, scroll="speechModelsPage")
        until(lambda: library.downloadJobs.rows()[0]["completedBytes"] == 128)
        click(window, "speechTabTTS")
        click(window, "speechInstall-" + tts.id, scroll="speechModelsPage")
        until(lambda: library.downloadCount == 2 and all(r["component"] for r in library.downloadJobs.rows()))
        assert library.busy and not library.operationBusy
        assert item(window, "speechLanguage").isEnabled()
        rows = library.downloadJobs.rows()
        assert {r["task"] for r in rows} == {"STT", "TTS"}
        assert {r["component"] for r in rows} == {stt.id + ".onnx", tts.id + ".onnx"}
        assert all(r["language"] == "en" and r["progress"] == 0.125 for r in rows)
        changes = QSignalSpy(library.modelsChanged)
        QTest.qWait(350)
        assert changes.count() == 0
        click(window, "cancelDownload-" + rows[0]["jobId"])
        until(lambda: library.downloadJobs.rows()[0]["state"] == "cancelled")
        assert library.downloadJobs.rows()[1]["state"] == "running"
        gates[tts.id].set()
        until(lambda: not library.busy)
        gates[stt.id].set()
        click(window, "retryDownload-" + rows[0]["jobId"])
        until(lambda: not library.busy)
        assert all(r["state"] == "completed" for r in library.downloadJobs.rows())
        assert library.store.installed(stt) and library.store.installed(tts)
    finally:
        for gate in gates.values():
            gate.set()
