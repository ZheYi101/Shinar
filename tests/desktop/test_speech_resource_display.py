from threading import Event

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from shinar.local_speech.downloads import TransferEvent
from shinar.desktop.voice.continuous.state import CallEvent
from tests.support.qt import click, item, until
from tests.support.scenarios import workspace_of



def test_local_model_labels_separate_download_disk_and_unmeasured_ram(library_desktop):
    _, library, _, window, _, _ = library_desktop
    library.setFilter("en", "conversation")
    until(lambda: not library.busy and bool(library.models))
    row = library.models[0]
    assert "totalMiB" in library.storageUsage and row["cacheMiB"] == 0
    package = item(window, "speechPackageSize-" + row["id"])
    assert not package.isVisible()
    model_row = item(window, "speechModel-" + row["id"])
    summary = model_row.findChild(QObject, "speechPreparationSummary")
    assert summary.property("visible") and "需下载约" in summary.property("text")
    assert "安装" not in summary.property("text")
    click(window, "speechDetails-" + row["id"])
    assert package.isVisible() and "不含共享组件" in package.property("text")
    assert "安装空间预算约" in item(window, "speechCapacityHelp-" + row["id"]).property("helpText")
    memory = item(window, "speechMemory-" + row["id"]).property("text")
    assert "尚无本机实测" in memory and "0 MiB" not in memory
    assert "本地语音文件共" in item(window, "speechStorageUsage-total").property("text")


def test_continuous_file_completion_is_not_whole_setup_completion(desktop, monkeypatch):
    import shinar.desktop.voice.continuous.preparation as module

    vm, window, _, _, _, audio, _ = desktop
    call = vm.voice.call
    entered, release = Event(), Event()
    callbacks = []

    def runtime(root, runtime_id, *, cancel, stage, on_transfer):
        stage("speech_setup_wheels")
        on_transfer(TransferEvent("livekit-rtc.whl", "downloading", 11 * 1024**2, 11 * 1024**2))
        callbacks.append(on_transfer)
        entered.set()
        assert release.wait(6)
        stage("speech_setup_installing")

    def assets(root, *, cancel, on_transfer):
        on_transfer(TransferEvent("silero_vad.onnx", "verifying"))

    def sfu(root, *, download, cancel, on_transfer):
        on_transfer(TransferEvent("livekit-server.exe", "extracting"))

    async def fake_blocking(request, *, on_event, cancel):
        import asyncio
        operation = {"runtime": runtime, "continuous_assets": assets, "server": sfu}[request.operation]
        options = dict(request.options or {})
        options.update(cancel=cancel, on_transfer=lambda event: on_event("transfer", event))
        if request.operation == "runtime":
            options["stage"] = lambda stage: on_event("stage", stage)
        return await asyncio.to_thread(operation, *request.args, **options)

    monkeypatch.setattr(module, "run_blocking", fake_blocking)
    ws = workspace_of(window)
    ws.setCategory("audio")
    ws.navigate("settings")
    QTest.qWait(50)
    click(window, "prepareContinuousVoice", scroll="settingsOverview")
    try:
        until(lambda: entered.is_set() and call.setupProgress["progress"] == 1.0)
        assert call.connectionState == "preparing"
        assert "运行库" in item(window, "continuousSetupStage").property("text")
        assert item(window, "continuousSetupComponent").property("text") == "livekit-rtc.whl"
        assert "当前文件" in item(window, "continuousSetupFileProgress").property("text")
        assert "11.0" in item(window, "continuousSetupFileProgress").property("text")
        assert not item(window, "prepareContinuousVoice").isEnabled()
        assert audio.plays == 0
    finally:
        release.set()
    until(lambda: call.connectionState == "off")
    assert "已准备" in call.noticeText
    assert call.setupProgress["component"] == "livekit-server.exe"
    old_identity = call.preparation_snapshot.identity
    call.stop()
    call.receive_event(CallEvent(old_identity, "setup_transfer", value=TransferEvent("stale.wav", "downloading", 1, 2)))
    assert call.setupProgress["component"] != "stale.wav"


def test_continuous_storage_refresh_is_read_only_and_rejects_old_root(desktop, tmp_path):
    vm, _, _, _, _, audio, _ = desktop
    call = vm.voice.call
    (call.root / "downloads").mkdir(parents=True, exist_ok=True)
    (call.root / "downloads/test").write_bytes(b"x" * 1024**2)
    call.refreshSetupStorage()
    until(lambda: call.setupStorage.get("totalMiB") == 1.0)
    call.root = tmp_path / "another-cache"
    call.receive_event(CallEvent("", "setup_storage", value=("old-root", 0, {"totalMiB": 999})))
    assert call.setupStorage == {} and call.connectionState == "off"
    assert not vm.busy and audio.plays == 0


def test_model_library_keeps_controls_and_on_demand_help_accessible(library_desktop):
    _, library, _, window, _, _ = library_desktop
    until(lambda: not library.busy)
    assert not item(window, "speechLibraryStatus").isVisible()
    for width in (360, 1180):
        window.setWidth(width)
        QTest.qWait(80)
        for name in ("speechLanguage", "speechScenario", "openSpeechCompute", "speechBenchmarkHelp"):
            control = item(window, name)
            end = control.mapToScene(QPointF(control.width(), control.height()))
            assert control.isVisible() and 0 < end.x() <= width and end.y() < window.height()
        assert item(window, "speechModelsPage").height() > window.height() / 2
        help_button = item(window, "speechBenchmarkHelp")
        help_button.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Space)
        popup = window.findChild(QObject, "speechBenchmarkHelp-popup")
        until(lambda: popup.property("opened"))
        assert "内置示例" in help_button.property("helpText")
        QTest.keyClick(window, Qt.Key.Key_Escape)
        until(lambda: not popup.property("visible"))
