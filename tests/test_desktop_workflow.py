"""Qt event-loop and real QML interaction checks; speech transport is synthetic."""
from __future__ import annotations

import asyncio
import json
import io
import os
from pathlib import Path
from time import monotonic, sleep
import wave

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPointF, QSettings, Qt, Signal, QThread, QTimer
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from lingualoop.application import LearningWorkbench
from lingualoop.desktop.app import create_engine
from lingualoop.desktop.preferences import DesktopPreferences
from lingualoop.desktop.viewmodel import LearningViewModel
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider


def pcm_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x10\x00\xf0\xff" * 800)
    return output.getvalue()


class FakeAudio(QObject):
    recorded = Signal(bytes)
    errorOccurred = Signal(str)
    stateChanged = Signal(str)
    durationChanged = Signal(int)
    devicesChanged = Signal()
    queueChanged = Signal()
    segmentStarted = Signal(object)
    input_devices = [{"id": "input", "name": "Test microphone"}]
    output_devices = [{"id": "output", "name": "Test speaker"}]

    def __init__(self):
        super().__init__()
        self.plays = 0
        self.cleared = False
        self.fail_play = False
        self.segments = []
        self.queued = []
        self.generation = ""
        self.auto_finish = True

    def start_recording(self):
        self.stateChanged.emit("recording")
        self.durationChanged.emit(1)

    def stop_recording(self):
        self.recorded.emit(pcm_wav())

    def cancel_recording(self):
        self.stateChanged.emit("idle")

    def play(self, audio):
        assert audio == pcm_wav()
        if self.fail_play:
            self.fail_play = False
            self.stateChanged.emit("error")
            self.errorOccurred.emit("播放失败，文字回复已保留。")
        else:
            self.plays += 1
            self.stateChanged.emit("playing")

    def stop_playback(self):
        self.generation = ""
        self.queued = []
        self.stateChanged.emit("idle")
        self.queueChanged.emit()

    @property
    def queued_count(self):
        return len(self.queued)

    def begin_playback(self, generation):
        self.stop_playback()
        self.generation = generation

    def enqueue(self, segment, generation):
        assert QThread.currentThread() == QGuiApplication.instance().thread()
        if generation != self.generation:
            raise RuntimeError("stale_audio_generation")
        if len(self.queued) >= 3:
            return False
        if self.fail_play:
            self.fail_play = False
            raise RuntimeError("playback_failed")
        self.plays += 1
        self.segments.append(segment)
        self.queued.append(segment)
        self.stateChanged.emit("playing")
        self.segmentStarted.emit(segment)
        self.queueChanged.emit()
        if self.auto_finish:
            QTimer.singleShot(10, lambda: self.finish_segment(generation, segment))
        return True

    def finish_segment(self, generation=None, segment=None):
        if generation is not None and generation != self.generation:
            return
        if self.queued and (segment is None or segment in self.queued):
            self.queued.remove(segment or self.queued[0])
        if not self.queued:
            self.stateChanged.emit("idle")
        self.queueChanged.emit()

    def clear(self):
        self.cleared = True
        self.stop_playback()


class FakeSpeech:
    def __init__(self):
        self.transcriptions = self.syntheses = 0
        self.fail_stt = self.fail_tts = False
        self.loops = []

    async def transcribe(self, audio):
        self.loops.append(asyncio.get_running_loop())
        self.transcriptions += 1
        await asyncio.sleep(0.01)
        if self.fail_stt:
            self.fail_stt = False
            raise RuntimeError("识别服务暂不可用。")
        return "昨日は友達に会いました。"

    async def synthesize(self, text):
        self.loops.append(asyncio.get_running_loop())
        self.syntheses += 1
        await asyncio.sleep(0.01)
        if self.fail_tts:
            self.fail_tts = False
            raise RuntimeError("合成服务暂不可用。")
        return pcm_wav()


class TrackedProvider(MockLearningLLMProvider):
    def __init__(self):
        self.loops = []
        self.reply_calls = 0
        self.fail_reply = False

    async def analyze_material(self, **kwargs):
        self.loops.append(asyncio.get_running_loop())
        return await super().analyze_material(**kwargs)

    async def generate_reply(self, **kwargs):
        self.loops.append(asyncio.get_running_loop())
        self.reply_calls += 1
        await asyncio.sleep(0.02)
        if self.fail_reply:
            self.fail_reply = False
            raise RuntimeError("回复服务暂不可用。")
        return await super().generate_reply(**kwargs)

    async def stream_reply(self, **kwargs):
        reply = await self.generate_reply(**kwargs)
        for position in range(0, len(reply), 8):
            yield reply[position:position + 8]
            await asyncio.sleep(0.02)


@pytest.fixture(scope="module")
def qt_app():
    app = QGuiApplication.instance() or QGuiApplication(["lingualoop-interaction-test"])
    if os.name == "nt":
        for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    return app


def until(predicate, timeout=5000):
    deadline = monotonic() + timeout / 1000
    while not predicate() and monotonic() < deadline:
        QGuiApplication.instance().processEvents()
        sleep(0.01)
    assert predicate()


def item(window, name):
    result = window.findChild(QQuickItem, name)
    if result is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name:
                result = candidate
                break
            pending.extend(candidate.childItems())
    assert result is not None, name
    return result


def click(window, name, *, scroll=None):
    target = item(window, name)
    if scroll:
        view = item(window, scroll)
        flick = view.property("contentItem")
        # Scroll against the live, polished geometry. A first data notification
        # can change card heights after the first requested content position.
        for _ in range(5):
            target = item(window, name)
            y = target.mapToItem(flick, QPointF()).y() + flick.property("contentY")
            flick.setProperty("contentY", max(0, min(y - 16, flick.property("contentHeight") - flick.height())))
            QTest.qWait(60)
            target = item(window, name)
            viewport_point = target.mapToItem(view, QPointF(target.width() / 2, target.height() / 2))
            if 0 <= viewport_point.x() < view.width() and 0 <= viewport_point.y() < view.height():
                break
        assert 0 <= viewport_point.x() < view.width() and 0 <= viewport_point.y() < view.height(), (name, viewport_point)
    # Qt Quick polishes Flow/Layout geometry asynchronously, including when a
    # record action changes the visible controls. Wait for a stable hit point.
    previous_geometry = None
    stable = 0
    for _ in range(12):
        target = item(window, name)
        center = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
        geometry = (center.x(), center.y(), target.width(), target.height())
        stable = stable + 1 if geometry == previous_geometry else 0
        if stable >= 2:
            break
        previous_geometry = geometry
        QTest.qWait(20)
    assert stable >= 2, (name, "Control geometry did not settle")
    assert target.isVisible(), name
    assert target.isEnabled(), name
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseMove(window, point)
    QTest.qWait(20)
    # Hover processing may deliver a pending layout polish; press the current
    # center rather than a coordinate measured before that event processing.
    target = item(window, name)
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(20)
    try:
        assert target.property("down"), (name, "The actual control did not receive the mouse press", point,
                                         target.mapToScene(QPointF(target.width() / 2, target.height() / 2)))
    finally:
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)


@pytest.fixture
def desktop(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUALOOP_KIRIGAMI_MODE", "off")
    provider, speech, audio = TrackedProvider(), FakeSpeech(), FakeAudio()
    database = tmp_path / "workflow.sqlite3"
    workbench = LearningWorkbench(provider, event_store=SQLiteStore(database))
    prefs = DesktopPreferences(QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat))
    vm = LearningViewModel(workbench, "Mock 调试", preferences=prefs,
                           stt_provider=speech, tts_provider=speech, audio_controller=audio)
    engine = create_engine(vm, window_settings=QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat))
    window = engine.rootObjects()[0]
    window.setProperty("width", 1180)
    window.setProperty("height", 900)
    window.requestActivate()
    QTest.qWait(50)
    scaffold = next(obj for obj in window.findChildren(QObject) if obj.metaObject().indexOfProperty("currentPage") >= 0)
    try:
        yield vm, window, scaffold, provider, speech, audio, database
    finally:
        vm.close()
        assert not vm._worker._thread or not vm._worker._thread.is_alive()
        assert audio.cleared
        window.close()
        window.property("workspaceController").close()
        engine.deleteLater()
        qt_app.processEvents()


def workspace_of(window):
    return window.property("workspaceController")


def load_material(vm, title, content, source, target, native, level):
    from lingualoop.core import LanguageEnum, ProficiencyLevel
    vm.run_operation("保存材料", lambda: vm.workbench.load_material(
        title=title, content=content, source_language=LanguageEnum(source),
        target_language=LanguageEnum(target), native_language=LanguageEnum(native),
        learner_level=ProficiencyLevel(level), auto_prepare=False,
    ), vm._after_material_loaded)


def load_and_start(vm, window):
    load_material(vm, "放課後の約束", "放課後、二人は喫茶店で話した。離れても友達でいようと約束した。",
                    "japanese", "japanese", "chinese", "B1")
    until(lambda: not vm.busy)
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    until(lambda: ws.documentReady)
    click(window, "readWholeMaterialButton")
    click(window, "saveScopeButton")
    until(lambda: not vm.busy)
    assert ws.material["confirmed"]
    ws.newThreadPage()
    QTest.qWait(60)
    click(window, "startDiscussionButton")
    until(lambda: vm.sessionActive and not vm.busy)


def test_service_balance_error_is_actionable_and_saved_material_survives(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    class BalanceError(Exception):
        status_code = 402
    async def fail(**kwargs):
        raise BalanceError('PRIVATE_PROVIDER_BODY_MUST_NOT_BE_SHOWN')
    async def fail_stream(**kwargs):
        await fail(**kwargs)
        yield ''
    provider.stream_reply = fail_stream
    load_material(vm, 'Book', 'Two friends met at the station.', 'english', 'english', 'chinese', 'B1')
    until(lambda: not vm.busy)
    assert not vm.errorMessage  # Import is local, including with an empty AI balance.
    vm.confirmReadingPercent(100)
    until(lambda: not vm.busy)
    workspace_of(window).browseMaterial(vm.selectedMaterialId)
    workspace_of(window).startThread()
    until(lambda: not vm.busy)
    vm.sendMessage('I liked the friends meeting again.')
    until(lambda: not vm.busy)
    assert '402' in vm.messages[-1]['replyError'] and '余额不足' in vm.messages[-1]['replyError']
    assert 'PRIVATE_PROVIDER' not in vm.messages[-1]['replyError']
    assert vm.hasMaterial and vm.materialTitle == 'Book'
    assert SQLiteStore(database).list_materials()[0].content == 'Two friends met at the station.'


def test_long_novel_summary_does_not_take_over_material_space(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    vm.draft = 'Unsent thought.'
    ws.browseMaterial(vm.selectedMaterialId)
    assert ws.route == 'material' and len(ws.threads) == 1
    assert vm.draft == 'Unsent thought.' and vm.sessionActive
    assert window.findChild(QObject, 'materialSummaryText') is None


def test_empty_library_has_no_form_modal(desktop):
    vm, window, scaffold, *_ = desktop
    ws = workspace_of(window)
    ws.navigate('import')
    QTest.qWait(100)
    assert ws.route == 'import' and not vm.hasSession
    assert window.findChild(QObject, 'sessionHistoryDialog') is None
    assert not window.grabWindow().isNull()


def test_topic_browsing_groups_provider_synonyms_into_a_small_vocabulary():
    from lingualoop.desktop.viewmodel import _topic_category_label
    assert {_topic_category_label(value) for value in ['narrative reliability', 'Narrator reliability and obsession',
        'narration, character motivation', '叙事可靠性', 'author\'s defense', 'literary criticism']} == {'叙述与文体'}
    assert _topic_category_label('relationships, choices, consequences') == '人物关系'
    assert _topic_category_label('character motivation') == '人物'
    assert _topic_category_label('ending') == '故事与情节'
    assert _topic_category_label('a previously unseen category') == '综合讨论'


def test_material_threads_preserve_unfinished_threads_and_drafts(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    vm.draft = 'First draft.'
    first_id = vm._workbench.session.id
    ws.browseMaterial(vm.selectedMaterialId)
    ws.newThreadPage()
    ws.startThread()
    until(lambda: not vm.busy)
    second_id = vm._workbench.session.id
    assert second_id != first_id and SQLiteStore(database).get_session(first_id).status.value == 'active'
    vm.draft = 'Second draft.'
    ws.openThread(first_id)
    assert vm.draft == 'First draft.' and vm.sessionActive
    ws.openThread(second_id)
    assert vm.draft == 'Second draft.' and len(ws.threads) == 2


def test_qml_three_voice_turns_retries_and_restart(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    load_and_start(vm, window)
    callbacks = []
    vm.messageSent.connect(lambda: callbacks.append(QThread.currentThread()))
    assert scaffold.property("currentPage") == 1
    speech.fail_stt = True
    vm.draft = "This independent text draft must survive."
    for turn in range(3):
        click(window, "recordButton")
        assert vm.voiceState == "recording" and vm.recordingSeconds == 1
        if turn == 1:
            speech.fail_tts = True
        click(window, "recordButton")
        vm.stopRecording()  # Duplicate recorder/stop events must not submit twice.
        until(lambda: not vm.busy)
        if turn == 0:
            assert vm.voice.transcriptionError and vm.canRetryTranscription
            click(window, "retryTranscriptionButton")
            until(lambda: not vm.busy)
        assert len(vm.messages) == 1 + 2 * (turn + 1)
        assert vm.draft == "This independent text draft must survive."
        assert vm._workbench.session.messages[-2].metadata["confirmation_kind"] == "automatic_transcript"
        if turn == 1:
            assert vm.messages[-1]["speechError"]
            calls = provider.reply_calls
            click(window, "retrySpeech-" + vm.messages[-1]["id"])
            until(lambda: not vm.busy)
            assert provider.reply_calls == calls and not vm.messages[-1]["speechError"]
        assert vm.voiceState == "idle"
    assert provider.reply_calls == 3 and speech.transcriptions == 4
    assert len({id(loop) for loop in provider.loops + speech.loops}) == 1
    assert callbacks and all(thread == QGuiApplication.instance().thread() for thread in callbacks)
    click(window, "conversationMenuButton")
    click(window, "finishDiscussionButton")
    until(lambda: not vm.busy)
    assert not vm.sessionActive and scaffold.property("currentPage") == 2
    restored = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(database))
    assert restored.session.status.value == "completed"
    assert len(restored.session.messages) == 7
    assert restored.session.topic is None and vm.selectedTopicId == ""
    assert "audio" not in restored.session.model_dump_json()


def test_resizing_theme_keyboard_and_draft_survive(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    load_and_start(vm, window)
    draft = "長い日本語の草稿。" * 30 + "\n中文输入也保留。"
    vm.draft = draft
    topic = vm.topicTitle
    for theme in ("light", "dark", "system"):
        vm.preferences.setValue("themeMode", theme)
        for width in (360, 600, 800, 1180, 1440):
            window.setProperty("width", width)
            window.setProperty("height", 800)
            QTest.qWait(30)
            assert scaffold.property("compact") == (width < 600)
            assert workspace_of(window).sourceOpen is False
            assert vm.draft == draft and vm.topicTitle == topic
            for name in ("recordButton", "sendMessageButton"):
                button = item(window, name)
                assert button.height() >= 36 and button.width() >= 36
                point = button.mapToScene(QPointF(button.width(), button.height()))
                assert point.x() <= width and point.y() <= 800
            # The filled send action must use its paired contrast color.
            send = item(window, "sendMessageButton")
            color = send.property("contentColor")
            background = send.property("background").property("color")
            def luminance(value):
                channels = (value.redF(), value.greenF(), value.blueF())
                rgb = [part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4 for part in channels]
                return sum(part * weight for part, weight in zip(rgb, (0.2126, 0.7152, 0.0722)))
            lighter, darker = sorted((luminance(color), luminance(background)), reverse=True)
            assert (lighter + 0.05) / (darker + 0.05) >= 4.5
            assert not window.grabWindow().isNull()
    # A navigation round trip keeps the same editor; keyboard focus remains usable.
    click(window, "nav0")
    workspace_of(window).navigate("chat")
    QTest.qWait(50)
    editor = item(window, "messageInput")
    editor.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_End)
    QTest.keyClick(window, Qt.Key.Key_X)
    assert "x" in vm.draft.lower()
    assert scaffold.property("currentPage") == 1
    assert len(vm.messages) == 1


def test_reply_retry_preserves_confirmed_messages_and_playback_retry(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    load_and_start(vm, window)
    provider.fail_reply = True
    vm.draft = "昨日、友達に会いました。"
    click(window, "sendMessageButton")
    until(lambda: not vm.busy)
    assert vm.messages[-1]["replyError"] and vm.draft == "" and len(vm.messages) == 2
    assert vm.messages[-1]["role"] == "user"
    click(window, "retryReply-" + vm.messages[-1]["id"])
    until(lambda: not vm.busy)
    assert len(vm.messages) == 3
    calls, syntheses = provider.reply_calls, speech.syntheses
    audio.fail_play = True
    vm.speakReply()
    until(lambda: not vm.busy)
    assert vm.messages[-1]["speechError"]
    vm.speakReply()
    until(lambda: not vm.busy)
    assert provider.reply_calls == calls and speech.syntheses == syntheses
    vm.startRecording()
    vm.cancelRecording()
    assert vm.voiceState == "idle" and not vm.canRetryTranscription


def test_audio_controller_temporary_files_and_timer(qt_app):
    from lingualoop.desktop.audio import AudioController
    from PySide6.QtMultimedia import QMediaRecorder

    audio = AudioController()
    directory = audio._dir()
    path = directory / "recording.wav"
    path.write_bytes(pcm_wav())
    received = []
    audio.recorded.connect(received.append)
    audio._pending_recording = True
    audio._recording_state(QMediaRecorder.RecorderState.StoppedState)
    assert received == [pcm_wav()]
    assert not path.exists() and audio._timer.interval() == 60000
    audio.clear()
    assert not directory.exists() and not audio._timer.isActive()


def test_free_text_streaming_initial_draft_and_shortcut(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    # Text development does not need audio configuration.
    vm._stt = vm._tts = None
    vm.uiChanged.emit()
    load_material(vm, "放課後の約束", "放課後、二人は喫茶店で話した。離れても友達でいようと約束した。",
                    "japanese", "japanese", "chinese", "B1")
    until(lambda: not vm.busy)
    assert not vm.topics and not vm.materialPrepared
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    QTest.qWait(80)
    click(window, "readWholeMaterialButton")
    click(window, "saveScopeButton")
    until(lambda: not vm.busy)
    ws.newThreadPage()
    QTest.qWait(60)
    custom = item(window, "customTopicInput")
    custom.forceActiveFocus()
    for character in "friendship choices":
        QTest.keyClick(window, Qt.Key(ord(character.upper())))
    assert ws.openingDraft == "friendship choices"
    custom_title = ws.openingDraft
    click(window, "startDiscussionButton")
    until(lambda: vm.sessionActive and not vm.busy)
    assert scaffold.property("currentPage") == 1
    assert vm._workbench.session.topic is None and vm.draft == custom_title
    assert not vm.topics
    assert not item(window, "recordButton").isVisible()
    vm.draft = "私なら友達の選択を応援します。"
    editor = item(window, "messageInput")
    editor.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    until(lambda: bool(vm.streamingText))
    assert vm.busy and not vm.pendingUserText and len(vm.messages) == 2
    assert vm.messages[-1]["role"] == "user"
    assert item(window, "streamingReplyText").isVisible()
    assert item(window, "streamingReplyText").property("text") == vm.streamingText
    until(lambda: not vm.busy)
    assert len(vm.messages) == 3 and not vm.streamingText and not vm.pendingUserText
    assert "首字" in vm.responseTiming and "完整回复" in vm.responseTiming
    assert not vm.preparationStatus  # No reasoning call after just one turn.
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    until(lambda: scaffold.property("currentPage") == 0)
    QTest.keyClick(window, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    until(lambda: scaffold.property("currentPage") == 1)


def test_frameless_controls_and_window_geometry(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    assert window.flags() & Qt.WindowType.FramelessWindowHint
    click(window, "nav3")
    assert scaffold.property("currentPage") == 3
    click(window, "nav0")
    click(window, "nav2")
    assert scaffold.property("currentPage") == 2
    click(window, "nav0")
    assert all(item(window, "resize_" + edge).isVisible() for edge in
               ("top", "bottom", "left", "right", "topLeft", "topRight", "bottomLeft", "bottomRight"))
    before = window.geometry()
    click(window, "windowMaximizeButton")
    until(lambda: window.windowState() == Qt.WindowState.WindowMaximized)
    assert not item(window, "resize_top").isVisible()
    click(window, "windowMaximizeButton")
    until(lambda: window.windowState() == Qt.WindowState.WindowNoState)
    assert window.geometry() == before
    QTest.keyClick(window, Qt.Key.Key_F10, Qt.KeyboardModifier.AltModifier)
    assert window.windowState() == Qt.WindowState.WindowMaximized
    QTest.keyClick(window, Qt.Key.Key_F10, Qt.KeyboardModifier.AltModifier)
    assert window.windowState() == Qt.WindowState.WindowNoState
    click(window, "windowMinimizeButton")
    assert window.windowState() == Qt.WindowState.WindowMinimized
    window.showNormal()
    window.requestActivate()
    assert window.windowState() == Qt.WindowState.WindowNoState
    click(window, "secondaryMenuButton")
    QTest.keyClick(window, Qt.Key.Key_Escape)
    click(window, "windowCloseButton")
    until(lambda: not window.isVisible())


def test_material_poll_does_not_destroy_pressed_reading_confirmation(desktop):
    vm, window, scaffold, *_ = desktop
    load_material(vm, 'Polling race', 'A first paragraph.\n\nA final paragraph.', 'english', 'english', 'chinese', 'B1')
    until(lambda: not vm.busy)
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    QTest.qWait(100)
    target = item(window, 'readWholeMaterialButton')
    point = target.mapToScene(QPointF(target.width()/2,target.height()/2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    vm._poll_preparation()
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert ws.pendingEnd > 0
    assert not ws.material['confirmed']
    click(window,'saveScopeButton')
    until(lambda: not vm.busy)
    assert ws.material['confirmed']


def test_background_preparation_does_not_move_composer_actions(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    load_and_start(vm, window)
    vm._preparation_timer.stop()
    vm._preparation_state = "idle"
    vm._response_timing = ""
    vm.uiChanged.emit()
    QTest.qWait(50)
    target = item(window, "recordButton")
    before = target.mapToScene(QPointF(target.width() / 2, target.height() / 2))
    vm._preparation_state = "ready"
    vm._response_timing = "首字 0.25 秒 · 完整回复 0.80 秒"
    vm.uiChanged.emit()
    QTest.qWait(50)
    assert target.mapToScene(QPointF(target.width() / 2, target.height() / 2)) == before


def test_window_restore_clamps_removed_monitor_and_forwards_native_actions(qt_app, tmp_path):
    from PySide6.QtCore import QRect
    from lingualoop.desktop.window import DesktopWindowController
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    settings.setValue("normalGeometry", QRect(90000, 90000, 1180, 780))
    window = QQuickWindow()
    window.setMinimumWidth(360)
    window.setMinimumHeight(560)
    controller = DesktopWindowController(settings)
    controller.attach(window)
    assert window.screen().availableGeometry().intersects(window.geometry())
    controller.save()
    assert settings.value("normalGeometry") == window.geometry()
    class NativeWindow:
        state = Qt.WindowState.WindowNoState
        calls = []
        def startSystemMove(self): self.calls.append("move"); return True
        def startSystemResize(self, edges): self.calls.append(edges); return True
        def windowState(self): return self.state
    native = NativeWindow()
    controller._window = native
    assert controller.startMove()
    assert controller.startResize(Qt.Edge.BottomEdge.value | Qt.Edge.RightEdge.value)
    assert native.calls == ["move", Qt.Edge.BottomEdge | Qt.Edge.RightEdge]
    assert not controller.startResize(1024)
    native.state = Qt.WindowState.WindowMaximized
    assert not controller.startResize(Qt.Edge.RightEdge.value)
    window.close()


def test_partial_reading_is_explicit_and_optional_direction_only_fills_draft(desktop):
    vm, window, scaffold, provider, speech, audio, database = desktop
    vm._stt = vm._tts = None
    text = "友達が駅に戻ってきた。二人は再会を喜んだ。\n未読の結末には別れがある。"
    load_material(vm, "途中までの本", text, "japanese", "japanese", "chinese", "B1")
    until(lambda: not vm.busy)
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    QTest.qWait(100)
    passage = "友達が駅に戻ってきた。二人は再会を喜んだ。"
    ws.locateSentence(passage)
    click(window, 'saveScopeButton')
    until(lambda: not vm.busy)
    assert ws.material['confirmed']
    assert vm.materialNormalizedContent == passage
    ws.newThreadPage()
    QTest.qWait(50)
    assert "未読の結末" not in vm.analysisSummary
    assert not vm.suggestedDirections
    async def prepare(request):
        prepared = await MockLearningLLMProvider().prepare_focus(request)
        data = json.loads(prepared.content)
        data["directions"] = ["友達が戻った理由について話したい。"]
        return prepared.model_copy(update={"content": json.dumps(data, ensure_ascii=False)})
    provider.prepare_focus = prepare
    click(window, "startDiscussionButton")
    until(lambda: vm.sessionActive and not vm.busy)
    QTest.qWait(80)  # Wait for navigation and the first layout polish.
    send_position = item(window, "sendMessageButton").mapToScene(QPointF())
    for reply in ("友達が戻ってきてうれしいです。", "その説明は違う気がします。友達はなぜ駅に戻ったのでしょうか。"):
        item(window, "messageInput").setProperty("text", reply)
        click(window, "sendMessageButton")
        until(lambda: not vm.busy)
    until(lambda: bool(vm.suggestedDirections))
    until(lambda: vm._preparation_state == "ready")
    QTest.qWait(50)
    assert item(window, "sendMessageButton").mapToScene(QPointF()) == send_position
    confirmed = len(vm.messages)
    click(window, "suggestedDirection0", scroll="practiceScroll")
    assert vm.draft == "友達が戻った理由について話したい。"
    assert len(vm.messages) == confirmed  # Suggestion is never an automatic sent answer.
