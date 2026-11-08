"""Page-entry checks never submit speech, lock threads or call the dialogue model."""

import asyncio
from threading import Event
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtTest import QTest

from shinar.local_speech.profiles import LocalSpeechProvider
from tests.support.audio import pcm_wav
from tests.support.qt import until, item, click
from tests.support.scenarios import load_and_start, workspace_of




from tests.support.continuous import Probe

class LocalModels:
    def __init__(self):
        self.loads = {"stt": 0, "tts": 0}
        self.verifications = {"stt": 0, "tts": 0}
        self.resident = {"stt": True, "tts": True}
        self.languages = []
        self.errors = {}
        self.entered = Event()
        self.hold = False

    async def close(self):
        self.resident = {"stt": False, "tts": False}

    def enabled(self, task):
        return True

    def worker_pid(self, task):
        return 123 if self.resident[task] else None

    def provider(self, task):
        service = self

        class Bound(LocalSpeechProvider):
            async def bind(self, language):
                service.languages.append((task, language))
                self.profile = SimpleNamespace(idle_seconds=120)
                return self

            async def prepare(self):
                service.loads[task] += 1
                service.entered.set()
                while service.hold:
                    await asyncio.sleep(0.01)
                if task in service.errors:
                    raise ValueError(service.errors[task])

            async def synthesize(self, text):
                return pcm_wav()

            async def verify(self):
                service.verifications[task] += 1

        return Bound(self, task)


def configure(vm, monkeypatch, *, local=True):
    import shinar.desktop.voice.readiness as module

    monkeypatch.setattr(module, "managed_status", lambda *a: {"prepared": True})
    monkeypatch.setattr(module, "prepared_assets", lambda *a: True)
    readiness = vm.voice.preflight
    probes = []

    def probe():
        result = Probe()
        probes.append(result)
        return result

    readiness.probe_factory = probe
    models = LocalModels()
    if local:
        vm._local_speech = models
    return readiness, models, probes


def states(readiness):
    return {row["id"]: row["state"] for row in readiness.checks}


def test_qml_page_entry_checks_devices_and_loads_models_before_start(desktop, monkeypatch):
    vm, window, _, provider, speech, _, _ = desktop
    readiness, models, probes = configure(vm, monkeypatch)
    assert not probes and models.loads == {"stt": 0, "tts": 0}
    load_and_start(vm, window)
    until(lambda: not readiness.busy and not vm.busy)
    assert set(states(readiness).values()) == {"ready"}
    assert models.loads == {"stt": 1, "tts": 1}
    assert models.verifications == {"stt": 1, "tts": 1}
    assert ("stt", "ja") in models.languages and ("tts", "ja") in models.languages
    assert probes[0].started and probes[0].closed and readiness._probe is None
    assert item(window, "voiceReadinessPanel").isVisible()
    assert "已就绪" in item(window, "voiceReadiness-stt").property("text")
    assert vm.voice.call.process is None and not vm.voice.active and not vm.busy
    before = len(vm.messages), provider.reply_calls, speech.transcriptions, speech.syntheses
    vm.draft = "This stays editable during checks."
    vm.sessionChanged.emit()
    vm.uiChanged.emit()
    vm.preferences.setValue("themeMode", "dark")
    QTest.qWait(60)
    assert models.loads == {"stt": 1, "tts": 1}
    assert all(p.closed for p in probes)
    assert before == (len(vm.messages), provider.reply_calls, 0, 0)
    assert not workspace_of(window).threadLocked


def test_checks_are_independent_and_retry_uses_current_language(desktop, monkeypatch):
    vm, window, _, _, _, _, _ = desktop
    readiness, models, _ = configure(vm, monkeypatch)
    models.errors["stt"] = "speech_model_not_selected"
    load_and_start(vm, window)
    until(lambda: not readiness.busy and not vm.busy)
    assert states(readiness)["stt"] == "error" and states(readiness)["tts"] == "ready"
    assert readiness.needsModelSettings and not vm.busy
    assert "日语" in next(r["error"] for r in readiness.checks if r["id"] == "stt")
    models.errors.clear()
    click(window, "retryVoiceReadiness")
    until(lambda: not readiness.busy)
    assert states(readiness)["stt"] == "ready"
    models.resident["tts"] = False
    readiness.refreshResidency()
    assert states(readiness)["tts"] == "released" and models.loads["tts"] == 2
    # A setting change does not replace the target language frozen in the session.
    vm.preferences.setValue("targetLanguage", "english")
    QTest.qWait(50)
    assert models.loads["stt"] == 2 and all(lang == "ja" for _, lang in models.languages)


def test_hidden_or_reconfigured_page_rejects_old_model_completion(desktop, monkeypatch):
    vm, window, _, provider, _, _, _ = desktop
    readiness, models, probes = configure(vm, monkeypatch)
    models.hold = True
    load_and_start(vm, window)
    until(models.entered.is_set)
    assert readiness.busy and not vm.busy and not workspace_of(window).threadLocked
    assert not item(window, "continuousVoiceButton").isEnabled()
    vm.draft = "Draft during model loading."
    old = readiness._job
    workspace_of(window).navigate("settings")
    until(lambda: not readiness._visible)
    readiness._progress.emit(old, "stt", ("ready", "", 0, True))
    models.hold = False
    QTest.qWait(50)
    assert states(readiness)["stt"] != "ready" and readiness._probe is None
    workspace_of(window).navigate("chat")
    until(lambda: readiness._visible and not readiness.busy)
    assert states(readiness)["stt"] == "ready" and probes[-1].closed
    before = provider.reply_calls
    readiness.close()
    readiness._progress.emit(old, "stt", ("error", "speech_model_not_selected", 0))
    QTest.qWait(30)
    assert vm.draft == "Draft during model loading." and provider.reply_calls == before


def test_permission_and_delayed_probe_cannot_record_after_leaving(desktop, monkeypatch):
    import shinar.desktop.voice.readiness as module

    vm, window, _, _, speech, _, _ = desktop
    readiness, _, probes = configure(vm, monkeypatch, local=False)
    callbacks = []
    app = SimpleNamespace(
        checkPermission=lambda p: Qt.PermissionStatus.Undetermined,
        requestPermission=lambda p, c, cb: callbacks.append(cb),
        translate=module.QCoreApplication.translate,
    )
    monkeypatch.setattr(module, "QCoreApplication", SimpleNamespace(
        instance=lambda: app, translate=app.translate,
    ))
    load_and_start(vm, window)
    until(lambda: len(callbacks) == 1)
    workspace_of(window).navigate("settings")
    QTest.qWait(30)
    callbacks[0](SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    assert not probes
    workspace_of(window).navigate("chat")
    until(lambda: len(callbacks) == 2)
    callbacks[1](SimpleNamespace(status=lambda: Qt.PermissionStatus.Denied))
    until(lambda: not readiness.busy)
    assert states(readiness)["microphone"] == "error"
    assert states(readiness)["stt"] == "configured"
    assert speech.transcriptions == 0
    # Existing automatic reading of the opening message is separate from preflight.
    assert speech.syntheses == 1


def test_auto_read_disabled_and_config_changes_do_not_reload_during_call(desktop, monkeypatch, tmp_path):
    from tests.support.continuous import configure_call
    vm, window, _, _, _, _, _ = desktop
    readiness, models, _ = configure(vm, monkeypatch)
    vm.preferences.setValue("autoReadReplies", False)
    load_and_start(vm, window)
    until(lambda: not readiness.busy)
    assert states(readiness)["tts"] == "disabled" and models.loads["tts"] == 0
    call = configure_call(vm, monkeypatch, tmp_path)
    call.start()
    until(lambda: call.connectionState == "active" and not call.muted)
    vm.preferences.setValue("autoReadReplies", True)
    vm._local_speech_configuration()
    QTest.qWait(30)
    assert models.loads["tts"] == 0
    call.stop()
    until(lambda: call.connectionState == "off")
    vm.voice.notify()
    until(lambda: not readiness.busy)
    assert models.loads["tts"] == 1


def test_microphone_probe_checks_frames_and_releases_without_publishing(qt_app, monkeypatch):
    import shinar.desktop.voice.readiness as module
    from PySide6.QtMultimedia import QtAudio

    class Input(QObject):
        readyRead = Signal()

        def bytesAvailable(self):
            return 1920

        def readAll(self):
            reads.append(True)
            return b"\0" * 1920

    class Source(QObject):
        stateChanged = Signal()

        def setBufferSize(self, size):
            pass

        def start(self):
            return Input(self)

        def error(self):
            return QtAudio.Error.NoError

        def stop(self):
            stops.append(True)

    reads, stops, result = [], [], []
    device = SimpleNamespace(id=lambda: b"input")
    monkeypatch.setattr(module, "QMediaDevices", SimpleNamespace(audioInputs=lambda: [device]))
    monkeypatch.setattr(module.PcmAudioBridge, "_format", lambda d: (
        SimpleNamespace(bytesForDuration=lambda us: 7680), None,
    ))
    monkeypatch.setattr(module, "QAudioSource", lambda *a: Source())
    probe = module.MicrophoneProbe(SimpleNamespace(selected_input_id=b"input".hex()))
    probe.finished.connect(result.append)
    probe.start()
    assert result == [""] and reads == stops == [True]
    assert probe.source is probe.io is None and not probe._timer.isActive()
    probe._state()
    probe._timer.timeout.emit()
    assert result == [""]

