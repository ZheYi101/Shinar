"""Real QML interaction with synthetic PCM/RTC; never evidence of physical speech."""

from shinar.desktop.voice.continuous.state import CallEvent

import asyncio
from threading import Event
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.support.audio import pcm_wav
from tests.support.qt import click, until, item
from tests.support.scenarios import load_and_start, workspace_of






from tests.support.continuous import SyntheticBridge, SyntheticRtc, configure_call as configure



def begin(vm, window, monkeypatch, tmp_path):
    load_and_start(vm, window)
    call = configure(vm, monkeypatch, tmp_path)
    click(window, "continuousVoiceButton")
    until(lambda: call.connectionState == "active" and not call.muted)
    return call


def speak(call, identity, revision=1):
    call.process.event("input_started", utterance=identity, revision=revision)
    QTest.qWait(30)
    call.process.event("utterance", pcm_wav(), utterance=identity, revision=revision)


def test_qml_three_automatic_turns_keep_typed_draft_and_thread_lock(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    assert item(window, "mockDialogueNotice").property("visible")
    assert "Mock" in item(window, "mockDialogueNotice").property("text")
    vm.draft = "My independent draft 😀."
    for i in range(3):
        speak(call, str(i))
        until(lambda: provider.reply_calls == i + 1 and vm.messages[-1]["role"] == "assistant")
        until(lambda: call.replyState == "idle" and call.outputState == "idle")
    assert len(vm.messages) == 7 and vm.draft == "My independent draft 😀."
    assert vm.busy and workspace_of(window).threadLocked
    assert not call.canSendText and call.bridge.frames
    click(window, "muteMicrophoneButton")
    until(lambda: call.canSendText)
    click(window, "sendMessageButton")
    until(lambda: provider.reply_calls == 4 and vm.messages[-1]["role"] == "assistant")
    assert vm.draft == "" and call.muted
    process = call.process
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)
    assert process.closed and vm.sessionActive


def test_qml_barge_in_cancels_old_reply_and_rejects_late_audio(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    entered = Event()

    async def stream(**kwargs):
        provider.reply_calls += 1
        if provider.reply_calls == 1:
            yield "An unfinished answer. "
            entered.set()
            await asyncio.Event().wait()
        else:
            yield "The new answer."

    provider.stream_reply = stream
    speak(call, "one")
    until(lambda: entered.is_set() and call.bridge.frames)
    old_generation = call.snapshot.audio_generation
    first_turn = vm.messages[-1]["turnId"]
    vm.draft = "Still my next draft."
    speak(call, "two")
    until(lambda: provider.reply_calls == 2 and vm.messages[-1]["role"] == "assistant")
    assert vm._workbench.get_turn(first_turn).state == "cancelled"
    assert all(m["content"] != "An unfinished answer. " for m in vm.messages)
    assert vm.messages[-3]["replyNotice"]
    frames = len(call.bridge.frames)
    call.process.event("playback", b"old audio", generation=old_generation)
    QTest.qWait(30)
    assert all(data != b"old audio" for _, data in call.bridge.frames)
    assert vm.draft == "Still my next draft."
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_qml_recognition_failure_retries_while_muted_without_duplicate(
    desktop, monkeypatch, tmp_path
):
    vm, window, _, provider, speech, audio, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    speech.fail_stt = True
    speak(call, "failed")
    until(lambda: call.canRetryInput)
    assert call.muted and provider.reply_calls == 0
    click(window, "retryContinuousInput")
    until(lambda: provider.reply_calls == 1 and vm.messages[-1]["role"] == "assistant")
    assert len(vm.messages) == 3
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_reconnect_requires_explicit_microphone_resume_and_old_identity_is_ignored(
    desktop, monkeypatch, tmp_path
):
    vm, window, *_ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    old = call.process
    old.event("disconnected")
    until(lambda: call.process is not old and call.connectionState == "active")
    assert call.muted and not call.bridge.recording and old.closed
    old.event("utterance", pcm_wav(), utterance="stale", revision=1)
    QTest.qWait(50)
    assert len(vm.messages) == 1
    click(window, "muteMicrophoneButton")
    until(lambda: not call.muted)
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_playback_failure_keeps_generating_text_and_new_draft(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    gate = Event()

    async def stream(**kwargs):
        provider.reply_calls += 1
        yield "The first sentence. "
        while not gate.is_set():
            await asyncio.sleep(0.01)
        yield "The complete conclusion."

    provider.stream_reply = stream
    try:
        speak(call, "one")
        until(lambda: bool(call.bridge.frames))
        vm.draft = "My next thought."
        call.bridge.fault.emit("audio_output_failed")
        until(lambda: call.outputState == "idle")
        assert call.replyState == "generating"
        gate.set()
        until(lambda: vm.messages[-1]["role"] == "assistant")
        assert vm.messages[-1]["content"] == "The first sentence. The complete conclusion."
        assert vm.draft == "My next thought." and provider.reply_calls == 1
    finally:
        gate.set()
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_old_microphone_generation_cannot_submit_after_mute_resume(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    generation = call.snapshot.mic_generation
    click(window, "muteMicrophoneButton")
    click(window, "muteMicrophoneButton")
    until(lambda: not call.muted and call.snapshot.mic_generation > generation)
    call.process.event("input_started", utterance="old", revision=1, mic_generation=generation)
    call.process.event(
        "utterance", pcm_wav(), utterance="old", revision=1, mic_generation=generation
    )
    QTest.qWait(50)
    assert provider.reply_calls == 0 and speech.transcriptions == 0 and len(vm.messages) == 1
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_paused_speech_can_be_explicitly_sent_once_without_opening_microphone(
    desktop, monkeypatch, tmp_path
):
    vm, window, _, provider, speech, _, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    vm.draft = "Keep my separate draft."
    ws = workspace_of(window)
    ws.toggleSource()
    until(lambda: ws.documentReady)
    ws.selectSource(0, 8)
    source = ws.snapshot()
    ws.toggleSource()
    call.process.paused_audio = ({"utterance": "partial", "revision": 1}, pcm_wav())
    click(window, "muteMicrophoneButton")
    until(lambda: call.canSendPausedInput)
    ws.selectSource(8, 16)
    assert not call.bridge.recording and provider.reply_calls == 0
    assert "已保留" in call.noticeText
    call.process.event("utterance", pcm_wav(), utterance="late", revision=1)
    QTest.qWait(50)
    assert len(vm.messages) == 1 and speech.transcriptions == 0
    click(window, "sendPausedInputButton")
    call.sendPausedInput()  # Repeated callback must not enqueue a second send.
    until(lambda: len(vm.messages) == 3 and vm.messages[-1]["role"] == "assistant")
    assert len(vm.messages) == 3 and provider.reply_calls == 1 and speech.transcriptions == 1
    assert call.muted and not call.bridge.recording and not call.hasPendingInput
    assert vm.draft == "Keep my separate draft."
    assert vm.messages[-2]["source"]["quote"] == source.quote
    assert ws.snapshot().quote != source.quote


def test_pause_during_recognition_keeps_audio_and_text_send_does_not_discard_it(
    desktop, monkeypatch, tmp_path
):
    vm, window, _, provider, speech, _, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    entered = Event()
    original = speech.transcribe
    async def slow(audio):
        entered.set()
        await asyncio.Event().wait()
    speech.transcribe = slow
    speak(call, "pending")
    until(entered.is_set)
    click(window, "muteMicrophoneButton")
    until(lambda: call.canSendPausedInput)
    assert provider.reply_calls == 0 and len(vm.messages) == 1
    assert call.snapshot.retained_utterance == "pending"
    speech.transcribe = original
    vm.draft = "A separate typed message."
    click(window, "sendMessageButton")
    until(lambda: provider.reply_calls == 1 and vm.messages[-1]["role"] == "assistant")
    assert call.canSendPausedInput and call.snapshot.retained_utterance == "pending"
    click(window, "sendPausedInputButton")
    until(lambda: len(vm.messages) == 5 and vm.messages[-1]["role"] == "assistant")
    assert len(vm.messages) == 5 and not call.hasPendingInput and call.muted


def test_explicit_discard_keeps_microphone_paused_and_rejects_late_snapshot(
    desktop, monkeypatch, tmp_path
):
    vm, window, _, provider, speech, _, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    call.process.paused_audio = ({"utterance": "noise", "revision": 1}, pcm_wav())
    click(window, "muteMicrophoneButton")
    until(lambda: call.canSendPausedInput)
    old_pause = call.snapshot.pause_id
    click(window, "discardContinuousInput")
    until(lambda: not call.microphoneBusy)
    call.process.event("input_paused", pcm_wav(), utterance="noise", revision=2,
                       pause_id=old_pause, mic_generation=call.snapshot.mic_generation)
    QTest.qWait(50)
    assert not call.hasPendingInput and call.muted and not call.bridge.recording
    assert len(vm.messages) == 1 and provider.reply_calls == 0 and speech.transcriptions == 0


def test_pausing_microphone_keeps_the_confirmed_reply_running(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, _, _, _ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    finish = Event()
    async def stream(**kwargs):
        provider.reply_calls += 1
        yield "The first sentence. "
        while not finish.is_set():
            await asyncio.sleep(.01)
        yield "The reply is complete."
    provider.stream_reply = stream
    try:
        speak(call, "confirmed")
        until(lambda: call.replyState == "generating" and bool(call.bridge.frames))
        generation = call.runner.generation
        click(window, "muteMicrophoneButton")
        until(lambda: not call.microphoneBusy)
        assert call.muted and not call.bridge.recording and not call.hasPendingInput
        assert call.replyState == "generating" and call.runner.generation == generation
        finish.set()
        until(lambda: len(vm.messages) == 3 and vm.messages[-1]["role"] == "assistant")
        assert vm.messages[-1]["content"].endswith("The reply is complete.")
        assert provider.reply_calls == 1
    finally:
        finish.set()


def test_pcm_frames_do_not_refresh_hidden_settings_or_reopen_failed_output(
    desktop, monkeypatch, tmp_path
):
    import shinar.desktop.voice.continuous.preparation as module

    vm, window, *_ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    plans = []
    monkeypatch.setattr(
        module,
        "runtime_plan",
        lambda *args: plans.append(args) or SimpleNamespace(download_bytes=0, disk_bytes=0),
    )
    # The actual application keeps the settings page instantiated while chatting.
    call.componentsChanged.emit()
    assert plans
    plans.clear()
    changes = []
    call.changed.connect(lambda: changes.append(call.outputState))
    call.receive_event(CallEvent(call.snapshot.identity, "output_begin", 0, "test-output"))
    changes.clear()
    for _ in range(100):
        call.receive_event(CallEvent(call.snapshot.identity, "transport", 0, ({"kind": "playback", "generation": "test-output"}, b"\0" * 1920)))
    assert len(call.bridge.frames) == 100 and changes == ["playing"]
    assert not plans
    call.componentsChanged.emit()
    assert len(plans) == 1
    call.stop_speech()
    changes.clear()
    call.receive_event(CallEvent(call.snapshot.identity, "transport", 0, ({"kind": "playback", "generation": "test-output"}, b"stale")))
    assert call.outputState == "idle" and not changes
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_permission_denial_does_not_connect_and_late_grant_cannot_start_after_stop(
    desktop, monkeypatch, tmp_path
):
    import shinar.desktop.voice.continuous.runtime as module

    vm, window, *_ = desktop
    load_and_start(vm, window)
    call = configure(vm, monkeypatch, tmp_path)
    status = Qt.PermissionStatus.Denied
    callbacks = []
    permission_api = SimpleNamespace(
        checkPermission=lambda permission: status,
        requestPermission=lambda permission, context, callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        module,
        "QCoreApplication",
        SimpleNamespace(
            instance=lambda: permission_api, translate=module.QCoreApplication.translate
        ),
    )
    click(window, "continuousVoiceButton")
    assert call.connectionState == "failed" and call.process is None
    assert "权限" in call.errorText and not callbacks
    status = Qt.PermissionStatus.Undetermined
    click(window, "continuousVoiceButton")
    assert call.connectionState == "permission" and len(callbacks) == 1
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)
    callbacks[0](SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    assert call.process is None and call.connectionState == "off"


def test_permission_grant_connects_once_and_faults_are_actionable(desktop, monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.runtime as module

    vm, window, *_ = desktop
    load_and_start(vm, window)
    call = configure(vm, monkeypatch, tmp_path)
    callbacks = []
    permission_api = SimpleNamespace(
        checkPermission=lambda permission: (
            Qt.PermissionStatus.Granted if callbacks else Qt.PermissionStatus.Undetermined
        ),
        requestPermission=lambda permission, context, callback: callbacks.append(callback),
    )
    monkeypatch.setattr(
        module,
        "QCoreApplication",
        SimpleNamespace(
            instance=lambda: permission_api, translate=module.QCoreApplication.translate
        ),
    )
    click(window, "continuousVoiceButton")
    assert call.process is None
    callbacks[0](SimpleNamespace(status=lambda: Qt.PermissionStatus.Granted))
    until(lambda: call.connectionState == "active" and not call.muted)
    call.bridge.fault.emit("input_gap")
    assert call.muted and "传输中断" in call.errorText
    assert call.faults[-1]["code"] == "input_gap"
    assert not call.canOpenMicrophoneSettings
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_finished_reading_rejects_late_frames_before_next_user_utterance(
    desktop, monkeypatch, tmp_path
):
    vm, window, _, provider, *_ = desktop
    call = begin(vm, window, monkeypatch, tmp_path)
    speak(call, "one")
    until(
        lambda: (
            provider.reply_calls == 1
            and vm.messages[-1]["role"] == "assistant"
            and call.outputState == "idle"
        )
    )
    generation = call.process.generation
    frames = len(call.bridge.frames)
    assert not call.snapshot.audio_generation and not call.bridge.generation
    for _ in range(50):
        call.process.event("playback", b"late silence", generation=generation)
    QTest.qWait(50)
    assert call.outputState == "idle" and len(call.bridge.frames) == frames
    assert not call.faults and not call.muted
    click(window, "continuousVoiceButton")
    until(lambda: not vm.busy)


def test_missing_language_model_is_actionable_before_microphone_opens(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    vm.preferences.setValue("targetLanguage", "english")
    call = configure(vm, monkeypatch, tmp_path)
    async def missing(language):
        raise ValueError("speech_model_not_selected")
    speech.bind = missing
    message_count = len(vm.messages)
    click(window, "continuousVoiceButton")
    until(lambda: call.connectionState == "failed")
    assert "日语" in call.errorText and "STT" in call.errorText
    assert not call.bridge.recording and call.canOpenModelSettings
    assert call.faults[-1]["code"] == "speech_model_not_selected"
    assert item(window, "openSpeechModelSettings").isVisible()
    assert vm.speechLanguage == "ja" and len(vm.messages) == message_count
    click(window, "openSpeechModelSettings")
    workspace = workspace_of(window)
    until(lambda: workspace.route == "settings")
    assert workspace.settingsCategory == "local"
    assert item(window, "speechLanguage").property("currentIndex") == 0
    assert not call.bridge.recording and len(vm.messages) == message_count


def test_missing_tts_keeps_continuous_stt_and_text_reply_available(desktop, monkeypatch, tmp_path):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    async def missing(language):
        raise ValueError("speech_model_not_selected")
    vm._tts = SimpleNamespace(bind=missing)
    call = configure(vm, monkeypatch, tmp_path)
    click(window, "continuousVoiceButton")
    until(lambda: call.connectionState == "active" and not call.muted)
    assert "未启用朗读" in call.noticeText
    assert call.canOpenModelSettings
    before = len(vm.messages)
    speak(call, "without-tts")
    until(lambda: len(vm.messages) == before + 2 and call.replyState == "idle")
    assert vm.messages[-1]["role"] == "assistant"
    assert not vm.messages[-1].get("speechError")
    assert "output_begin" not in call.process.calls

