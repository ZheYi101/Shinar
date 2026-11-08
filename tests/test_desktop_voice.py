"""Speech bridge regression with real QML and synthetic devices, never a real mic."""

import asyncio
from threading import Event
from time import monotonic

from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer, QMediaDevices

from shinar.application import LearningWorkbench
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore

from test_desktop_workflow import (
    desktop,
    FakeAudio,
    FakeSpeech,
    TrackedProvider,
    click,
    item,
    load_and_start,
    until,
    workspace_of,
    qt_app,
)


def test_first_audio_precedes_full_reply_and_stop_does_not_stop_text(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    gate = Event()

    async def stream(**kwargs):
        provider.reply_calls += 1
        yield "She waited. "
        while not gate.is_set():
            await asyncio.sleep(0.005)
        yield "Then she left."

    provider.stream_reply = stream
    audio.segments.clear()
    audio.auto_finish = False
    vm.draft = "Why did she wait?"
    try:
        click(window, "sendMessageButton")
        until(lambda: bool(audio.segments))
        assert vm.busy and vm.voice.replyState == "generating"
        assert vm.voice.canStopSpeech and workspace_of(window).threadLocked
        assert vm.messages[-1]["role"] == "user" and len(vm.messages) == 2
        vm.draft = "My next, unsent thought."
        click(window, "stopSpeechButton")
        count = len(audio.segments)
        assert not audio.queued_count and vm.busy
        gate.set()
        until(lambda: not vm.busy)
        assert vm.draft == "My next, unsent thought."
        assert vm.messages[-1]["content"] == "She waited. Then she left."
        assert len(audio.segments) == count and provider.reply_calls == 1
        assert not vm.messages[-1]["speechError"]
        assert "player_started" in vm.voice.timings
    finally:
        gate.set()


def test_queue_backpressure_does_not_block_text_reader_and_holds_thread_lock(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    text_done = Event()

    async def stream(**kwargs):
        for i in range(8):
            yield f"Sentence {i}. "
            await asyncio.sleep(0.005)
        text_done.set()

    provider.stream_reply = stream
    audio.segments.clear()
    audio.auto_finish = False
    vm.draft = "Tell me more."
    click(window, "sendMessageButton")
    until(lambda: text_done.is_set() and audio.queued_count == 3 and vm.voice._pending_audio)
    assert vm.busy and len(audio.segments) == 3
    assert len(vm.voice._pending_audio) == 1
    assert workspace_of(window).threadLocked
    deadline = monotonic() + 8
    while vm.busy and monotonic() < deadline:
        audio.finish_segment()
        QTest.qWait(25)
        assert audio.queued_count <= 3
        if not vm.busy:
            break
    until(lambda: not vm.busy)
    # Look-ahead may group already available sentences into one synthesis.
    # Verify every sentence exactly once, in order, with contiguous audio indexes.
    assert [s.index for s in audio.segments] == list(range(len(audio.segments)))
    assert " ".join(" ".join(s.text for s in audio.segments).split()) == " ".join(
        f"Sentence {i}." for i in range(8)
    )
    assert len(vm.messages) == 3 and not workspace_of(window).threadLocked


def test_stt_only_auto_submits_and_auto_read_preference_persists(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    vm._tts = None
    load_and_start(vm, window)
    assert vm.voiceReady
    vm.draft = "Keep this text."
    click(window, "recordButton")
    click(window, "recordButton")
    until(lambda: not vm.busy)
    assert provider.reply_calls == 1 and speech.syntheses == 0
    assert vm.draft == "Keep this text."
    vm._tts = speech
    vm.preferences.setValue("autoReadReplies", False)
    vm.sendMessage("A typed follow-up.")
    until(lambda: not vm.busy)
    assert speech.syntheses == 0
    assert not DesktopPreferences(vm.preferences._settings).autoReadReplies
    vm.speakReply()
    until(lambda: not vm.busy)
    assert speech.syntheses and provider.reply_calls == 2
    vm.sendMessage("x" * 4001)
    until(lambda: not vm.busy)
    assert vm.errorMessage and vm.draft == "Keep this text."
    vm.sendMessage("A short follow-up.")
    until(lambda: not vm.busy)
    assert not vm.errorMessage and vm.draft == "Keep this text."


def test_empty_recognition_and_cancel_never_send_or_overwrite_draft(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    vm.draft = "Keep my draft."
    click(window, "recordButton")
    click(window, "cancelRecordingButton")
    assert not speech.transcriptions and not provider.reply_calls

    async def empty(audio):
        return "  "

    speech.transcribe = empty
    click(window, "recordButton")
    click(window, "recordButton")
    until(lambda: not vm.busy)
    assert vm.voice.transcriptionError and vm.voice.canRetryTranscription
    assert not provider.reply_calls and len(vm.messages) == 1
    assert vm.draft == "Keep my draft."
    click(window, "discardRecordingButton")
    assert not vm.voice.canRetryTranscription
    audio.recorded.emit(b"late invalid callback")
    QTest.qWait(30)
    assert not vm.busy and not provider.reply_calls


def test_failed_recording_keeps_original_source_through_retry(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    ws = workspace_of(window)
    ws.toggleSource()
    until(lambda: ws.documentReady)
    ws.selectSource(0, 8)
    original = ws.snapshot()
    speech.fail_stt = True
    vm.startRecording()
    vm.stopRecording()
    ws.selectSource(8, 16)
    vm.draft = "An independent draft."
    until(lambda: not vm.busy)
    vm.retryTranscription()
    until(lambda: not vm.busy)
    assert vm.messages[-2]["source"]["quote"] == original.quote
    assert vm.draft == "An independent draft."
    assert ws.snapshot().quote != original.quote and provider.reply_calls == 1


def test_restart_exposes_pending_reply_without_automatic_request(desktop, tmp_path):
    vm, window, _, provider, speech, audio, database = desktop
    load_and_start(vm, window)
    provider.fail_reply = True
    vm.sendMessage("A durable utterance.")
    until(lambda: not vm.busy)
    user_id, turn_id = vm.messages[-1]["id"], vm.messages[-1]["turnId"]
    vm.close()
    replacement = TrackedProvider()
    work = LearningWorkbench(replacement, event_store=SQLiteStore(database))
    prefs = DesktopPreferences(QSettings(str(tmp_path / "restart.ini"), QSettings.Format.IniFormat))
    restored = LearningViewModel(
        work,
        "Mock",
        preferences=prefs,
        audio_controller=FakeAudio(),
        stt_provider=FakeSpeech(),
        tts_provider=FakeSpeech(),
    )
    try:
        assert restored.messages[-1]["canRetryReply"] and not replacement.reply_calls
        restored.voice.retryReply(turn_id)
        until(lambda: not restored.busy)
        assert restored.messages[-2]["id"] == user_id
        assert replacement.reply_calls == 1 and len(restored.messages) == 3
    finally:
        restored.close()


def test_native_audio_queue_limits_order_and_stopped_is_not_end(qt_app, monkeypatch):
    from shinar.desktop.audio import AudioController
    from shinar.core.voice import SpeechSegment
    from test_desktop_workflow import pcm_wav

    class Player:
        def setSource(self, source):
            self.source = source

        def play(self):
            pass

        def stop(self):
            pass

    controller = AudioController()
    controller._player = Player()
    monkeypatch.setattr(QMediaDevices, "audioOutputs", lambda: [object()])
    controller.begin_playback("one")
    segments = [SpeechSegment.from_wav("turn", i, str(i), pcm_wav()) for i in range(4)]
    try:
        assert all(controller.enqueue(segment, "one") for segment in segments[:3])
        assert controller.queued_count == 3 and not controller.enqueue(segments[3], "one")
        first_path = controller._active_segment[1]
        controller._playback_state(QMediaPlayer.PlaybackState.StoppedState)
        assert controller.queued_count == 3 and controller._active_segment[0].index == 0
        controller._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert controller.queued_count == 2 and controller._active_segment[0].index == 1
        assert not first_path.exists() and controller.enqueue(segments[3], "one")
        controller.stop_playback()
        assert controller.queued_count == 0
        try:
            controller.enqueue(segments[0], "one")
            assert False, "old generation must be rejected"
        except RuntimeError:
            pass
    finally:
        directory = controller._dir()
        controller.clear()
        assert not directory.exists()


def test_device_failure_during_reply_keeps_text_and_draft(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    audio.auto_finish = False
    vm.sendMessage("Please explain.")
    until(lambda: bool(audio.queued_count))
    vm.draft = "My next thought."
    audio.errorOccurred.emit("播放设备已断开。")
    until(lambda: not vm.busy)
    assert vm.messages[-1]["role"] == "assistant" and vm.messages[-1]["speechError"]
    assert vm.draft == "My next thought." and not audio.queued_count


def test_new_audio_preference_is_interactive_at_narrow_width(desktop):
    vm, window, *_ = desktop
    window.setWidth(360)
    ws = workspace_of(window)
    ws.setCategory("audio")
    ws.navigate("settings")
    click(window, "autoReadRepliesSwitch")
    assert not vm.preferences.autoReadReplies
    click(window, "autoReadRepliesSwitch")
    assert vm.preferences.autoReadReplies


def test_worker_job_results_do_not_replace_legacy_completion(qt_app):
    from shinar.desktop.worker import AsyncWorker

    worker, started = AsyncWorker(), Event()
    legacy, jobs = [], []
    worker.completed.connect(lambda result, error: legacy.append((result, error)))
    worker.jobCompleted.connect(
        lambda identity, result, error: jobs.append((identity, result, error))
    )

    async def old():
        await asyncio.sleep(0.03)
        return "legacy"

    async def identified():
        return "identified"

    async def cancellable():
        started.set()
        await asyncio.Event().wait()

    async def cleanup():
        pass

    try:
        worker.submit(old)
        worker.submit_job("identified", identified)
        worker.submit_job("cancel", cancellable)
        until(started.is_set)
        worker.cancel_job("cancel")
        until(lambda: len(jobs) == 2 and legacy)
        assert legacy == [("legacy", "")]
        assert ("identified", "identified", "") in jobs
        assert ("cancel", None, "cancelled") in jobs
    finally:
        worker.close(cleanup)


def test_old_reply_can_retry_speech_without_fabricating_a_turn(desktop):
    vm, window, _, provider, speech, audio, _ = desktop
    load_and_start(vm, window)
    opening = vm.messages[0]
    assert not opening["turnId"]
    speech.fail_tts = True
    # Invalidate the complete opening cache to exercise synthesis failure.
    vm.voice.invalidate_cache()
    vm.speakReply()
    until(lambda: not vm.busy)
    assert vm.messages[0]["speechError"]
    click(window, "retrySpeech-" + opening["id"])
    until(lambda: not vm.busy)
    assert not vm.messages[0]["speechError"] and not provider.reply_calls
    assert not vm._workbench.session.messages[0].metadata.get("turn_id")
