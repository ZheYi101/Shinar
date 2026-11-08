"""Capture the shipped QML with isolated Mock data, optionally in a visible window.

Run with QT_QPA_PLATFORM=windows for a real Windows window; QT_SCALE_FACTOR tests
Qt rendering scale without changing the user's Windows settings.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from threading import Event
import wave

os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["RUN_REAL_AI_TESTS"] = "0"

from PySide6.QtCore import (
    QObject,
    QPointF,
    QSettings,
    Qt,
    QUrl,
    QMimeData,
    Signal,
    QTimer,
    qInstallMessageHandler,
)
from PySide6.QtGui import (
    QFontDatabase,
    QGuiApplication,
    QInputMethodEvent,
    QDragEnterEvent,
    QDropEvent,
)
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.speech_library import SpeechLibraryViewModel
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


def synthetic_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x10\x00\xf0\xff" * 800)
    return output.getvalue()


class SyntheticSpeech:
    hold = False
    fail_stt = False
    fail_tts = False

    async def transcribe(self, audio):
        assert audio == synthetic_wav()
        while self.hold:
            await asyncio.sleep(0.01)
        if self.fail_stt:
            self.fail_stt = False
            raise RuntimeError("synthetic_stt_failure")
        return "She remembered the promise, but she changed her mind."

    async def synthesize(self, text):
        if self.fail_tts:
            self.fail_tts = False
            raise RuntimeError("synthetic_tts_failure")
        return synthetic_wav()


class SyntheticAudio(QObject):
    """Owned test transport; never opens the user's microphone or speakers."""

    recorded = Signal(bytes)
    errorOccurred = Signal(str)
    stateChanged = Signal(str)
    durationChanged = Signal(int)
    devicesChanged = Signal()
    queueChanged = Signal()
    segmentStarted = Signal(object)
    input_devices = [{"id": "synthetic-in", "name": "合成录音（验证）"}]
    output_devices = [{"id": "synthetic-out", "name": "合成回放（验证）"}]

    def __init__(self):
        super().__init__()
        self._playback_timer = QTimer(self)
        self._playback_timer.setSingleShot(True)
        self._playback_timer.timeout.connect(self.finish_segment)
        self.queued = []
        self.generation = ""
        self.hold = False

    def start_recording(self):
        self._playback_timer.stop()
        self.stateChanged.emit("recording")
        self.durationChanged.emit(1)

    def stop_recording(self):
        self.recorded.emit(synthetic_wav())

    def cancel_recording(self):
        self.stateChanged.emit("idle")

    def play(self, audio):
        assert audio == synthetic_wav()
        self.stateChanged.emit("playing")
        self._playback_timer.start(100)

    def stop_playback(self):
        self._playback_timer.stop()
        self.queued = []
        self.generation = ""
        self.stateChanged.emit("idle")
        self.queueChanged.emit()

    @property
    def queued_count(self):
        return len(self.queued)

    def begin_playback(self, generation):
        self.stop_playback()
        self.generation = generation

    def enqueue(self, segment, generation):
        if generation != self.generation:
            raise RuntimeError("stale_generation")
        if len(self.queued) >= 3:
            return False
        self.queued.append(segment)
        if len(self.queued) == 1:
            self.segmentStarted.emit(segment)
        self.stateChanged.emit("playing")
        self.queueChanged.emit()
        if not self.hold:
            self._playback_timer.start(100)
        return True

    def finish_segment(self):
        if self.queued:
            self.queued.pop(0)
        if self.queued:
            self.segmentStarted.emit(self.queued[0])
            self._playback_timer.start(100)
        else:
            self.stateChanged.emit("idle")
        self.queueChanged.emit()

    def clear(self):
        self.stop_playback()


def enter_text(window, name, text):
    target = visible_item(window, name)
    target.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    event = QInputMethodEvent()
    event.setCommitString(text)
    QGuiApplication.sendEvent(target, event)
    QTest.qWait(50)
    assert target.property("text") == text


def wait_until(predicate, timeout=30):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(20)
    if not predicate():
        raise RuntimeError("UI verification timed out")


def visible_item(window, name):
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name and item.isVisible():
            return item
        pending.extend(item.childItems())
    raise AssertionError(name)


def click(window, name):
    QTest.qWait(100)
    target = visible_item(window, name)
    assert target.isEnabled(), name
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), name
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/ui-migration/captures"))
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--widths", default="360,600,800,1180,1440")
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--voice-states", action="store_true", help="Capture automatic speech and recovery states.")
    parser.add_argument(
        "--review-fixture",
        action="store_true",
        help="Create a denser library through QML for design comparison.",
    )
    args = parser.parse_args()
    if not args.visible:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    args.output.mkdir(parents=True, exist_ok=True)
    warnings = []
    qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    app = QGuiApplication([])
    if os.name == "nt":
        for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc", "seguisym.ttf", "seguiemj.ttf"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name)
            )
    with TemporaryDirectory(prefix="shinar-ui-validation-") as directory:
        root = Path(directory)
        prefs = DesktopPreferences(
            QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)
        )
        prefs.setValue("themeMode", args.theme)
        if args.review_fixture:
            prefs.setValue("targetLanguage", "english")
        speech, audio = SyntheticSpeech(), SyntheticAudio()
        vm = LearningViewModel(
            LearningWorkbench(
                MockLearningLLMProvider(), event_store=SQLiteStore(root / "library.db")
            ),
            "Mock",
            preferences=prefs,
            stt_provider=speech,
            tts_provider=speech,
            audio_controller=audio,
        )
        library = SpeechLibraryViewModel(root / "speech")
        engine = create_engine(
            vm,
            window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat),
            initial_visible=True,
            speech_library=library,
        )
        window, ws = engine.rootObjects()[0], engine.workspace
        window.setWidth(1440)
        window.setHeight(args.height)
        intermediate = []

        def capture_import_state(label):
            QTest.qWait(100)
            path = args.output / f"1440-{label}.png"
            assert window.grabWindow().save(str(path))
            intermediate.append(path.name)

        # Import through the actual page/controller. No fixture history is inserted into SQLite.
        sample = root / "sample.md"
        sample.write_text(
            "# At the station\n\nMina returned after five years. Her friend waited beside the clock.\n\n"
            "‘I thought you had forgotten,’ he said. She answered that remembering was the difficult part.\n\n"
            "# A different answer\n\n二人は窓のそばに座った。\n\n她把没有寄出的信放在桌上。😀",
            encoding="utf-8",
        )
        ws.navigate("import")
        QTest.qWait(100)
        target = visible_item(window, "importDropArea")
        point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(sample))])
        QGuiApplication.sendEvent(
            window,
            QDragEnterEvent(
                point.toPoint(),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        QGuiApplication.sendEvent(
            window,
            QDropEvent(
                point,
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        wait_until(lambda: not ws.inspecting and bool(ws.importFile))
        enter_text(
            window,
            "importTitleInput",
            "At the station"
            if args.review_fixture
            else "中日文長いタイトル · A different answer and an unfinished promise " * 3,
        )
        if args.review_fixture:
            capture_import_state("import-file")
        click(window, "commitImportButton")
        wait_until(lambda: not vm.busy and ws.documentReady)
        click(window, "readWholeMaterialButton")
        assert ws.pendingEnd == len(ws.workbench.get_material(ws.browsingMaterialId).content)
        click(window, "saveScopeButton")
        wait_until(lambda: not vm.busy)
        material_id = ws.browsingMaterialId
        ws.newThreadPage()
        click(window, "startDiscussionButton")
        wait_until(lambda: vm.sessionActive and not vm.busy)
        enter_text(
            window, "messageInput", "I think she returned because she wanted to explain herself."
        )
        click(window, "sendMessageButton")
        wait_until(lambda: not vm.busy)
        assert len(vm.messages) == 3 and not vm.draft
        click(window, "recordButton")
        assert vm.voiceState == "recording"
        click(window, "recordButton")
        wait_until(lambda: not vm.busy)
        assert len(vm.messages) == 5 and not vm.draft
        thread_id = vm._workbench.session.id
        if args.review_fixture:
            for thought in (
                "Understanding a character does not mean agreeing with their choices.",
                "Yesterday I go back to the letter, and I understand her choice differently.",
            ):
                wait_until(lambda: not ws.threadLocked)
                ws.newThreadPage()
                click(window, "startDiscussionButton")
                wait_until(lambda: not vm.busy and not ws.threadLocked)
                enter_text(window, "messageInput", thought)
                click(window, "sendMessageButton")
                wait_until(lambda: not vm.busy and not ws.threadLocked)
            vm.finishPractice()
            wait_until(lambda: not vm.busy)
            assert vm.reviewItems
            for title, body in (
                ("雨の日の本屋", "雨が降っていた。本屋の店主は古い手紙を見つけた。"),
                ("关于城市的一段播客", "人们讨论了城市里的公共空间，以及它如何改变日常生活。"),
            ):
                ws.navigate("import")
                click(window, "pasteImportTab")
                enter_text(window, "importTitleInput", title)
                enter_text(window, "importTextInput", body)
                if not intermediate or "1440-import-paste.png" not in intermediate:
                    capture_import_state("import-paste")
                click(window, "commitImportButton")
                wait_until(lambda: not vm.busy and ws.documentReady)
                click(window, "readWholeMaterialButton")
                click(window, "saveScopeButton")
                wait_until(lambda: not vm.busy)
                extra_material = ws.browsingMaterialId
                ws.newThreadPage()
                click(window, "startDiscussionButton")
                wait_until(lambda: not vm.busy and not ws.threadLocked)
                ws.toggleMaterial(extra_material)
            ws.openThread(thread_id)
        captures = []
        speech_timings = []

        def capture(label, width):
            QTest.qWait(140)
            # Measure the presented frame. On Windows a resized/occluded
            # software window may not polish its layouts until a render occurs.
            frame = window.grabWindow()
            def window_layout_settled():
                for name in ("windowMinimizeButton", "windowMaximizeButton", "windowCloseButton"):
                    button = visible_item(window, name)
                    position = button.mapToScene(QPointF())
                    if position.x() < 0 or position.x() + button.width() > window.width():
                        return False
                return True

            # Native DPI resizing and QML polish are asynchronous. Measure the
            # resulting layout, not a fixed delay after the resize request.
            try:
                wait_until(window_layout_settled, timeout=5)
            except RuntimeError:
                chain = []
                control = visible_item(window, "windowMinimizeButton")
                while control is not None:
                    chain.append((control.metaObject().className(), control.property("width"), control.property("implicitWidth")))
                    control = control.parentItem() if hasattr(control, "parentItem") else None
                window.grabWindow().save(str(args.output / f"{width}-{label}-layout-failure.png"))
                print({"requested_width": width, "actual_width": window.width(), "visibility": str(window.visibility()), "exposed": window.isExposed(), "layout_chain": chain}, flush=True)
                raise
            controls = {}
            for name in ("windowMinimizeButton", "windowMaximizeButton", "windowCloseButton",
                         "recordButton", "sendMessageButton", "cancelRecordingButton",
                         "stopSpeechButton"):
                candidates = [obj for obj in window.findChildren(QObject)
                              if obj.objectName() == name and hasattr(obj, "isVisible") and obj.isVisible()]
                if not candidates:
                    continue
                button = candidates[0]
                position = button.mapToScene(QPointF())
                controls[name] = [position.x(), position.y(), button.width(), button.height()]
                assert (
                    0 <= position.x() < window.width()
                    and position.x() + button.width() <= window.width()
                ), (label, name, controls[name])
            path = args.output / f"{width}-{label}.png"
            assert frame.save(str(path))
            captures.append(
                {
                    "view": label,
                    "width": window.width(),
                    "height": window.height(),
                    "dpr": window.devicePixelRatio(),
                    "path": path.name,
                    "windowControls": controls,
                }
            )

        try:
            for width in map(int, args.widths.split(",")):
                if args.visible:
                    window.showNormal()
                    window.setPosition(16, 16)
                    window.raise_()
                    window.requestActivate()
                    assert QTest.qWaitForWindowExposed(window, 5000)
                window.setWidth(width)
                window.setHeight(args.height if width > 600 else 780)
                ws.navigate("library")
                capture("library", width)
                ws.browseMaterial(material_id)
                capture("material", width)
                ws.navigate("reference")
                capture("reference", width)
                ws.browseMaterial(material_id)
                ws.newThreadPage()
                capture("new", width)
                ws.openThread(thread_id)
                if args.review_fixture:
                    ws.clearSource()
                    ws.clearSource()
                capture("chat", width)
                if args.voice_states:
                    provider = vm._workbench._provider
                    original_stream = provider.stream_reply
                    gate = Event()

                    async def slow_reply(**kwargs):
                        yield "She remembered the promise. "
                        while not gate.is_set():
                            await asyncio.sleep(0.01)
                        yield "Remembering did not mean she could keep it."

                    provider.stream_reply = slow_reply
                    enter_text(window, "messageInput", "未发送的文字草稿 · 次の考えも残しておきます。😀")
                    draft = vm.draft
                    click(window, "recordButton")
                    capture("voice-recording", width)
                    click(window, "cancelRecordingButton")
                    assert vm.draft == draft
                    speech.hold = audio.hold = True
                    try:
                        click(window, "recordButton")
                        click(window, "recordButton")
                        wait_until(lambda: vm.voice.recognitionState == "transcribing")
                        capture("voice-recognizing", width)
                        speech.hold = False
                        wait_until(lambda: audio.queued_count > 0 and vm.voice.replyState == "generating")
                        capture("voice-reply-and-play", width)
                        click(window, "stopSpeechButton")
                        gate.set()
                        wait_until(lambda: not vm.busy)
                        assert vm.draft == draft and not audio.queued_count
                        speech_timings.append({"width": width, "timings_ms": dict(vm.voice.timings)})
                    finally:
                        speech.hold = audio.hold = False
                        gate.set()
                        provider.stream_reply = original_stream
                    speech.fail_stt = True
                    click(window, "recordButton")
                    click(window, "recordButton")
                    wait_until(lambda: not vm.busy)
                    assert vm.voice.transcriptionError
                    capture("voice-recognition-error", width)
                    click(window, "discardRecordingButton")

                    async def failed_reply(**kwargs):
                        raise RuntimeError("synthetic_reply_failure")
                        yield ""

                    provider.stream_reply = failed_reply
                    enter_text(window, "messageInput", "Can you explain her decision?")
                    click(window, "sendMessageButton")
                    wait_until(lambda: not vm.busy)
                    capture("voice-reply-error", width)
                    provider.stream_reply = original_stream
                    click(window, "retryReply-" + vm.messages[-1]["id"])
                    wait_until(lambda: not vm.busy)
                    speech.fail_tts = True
                    enter_text(window, "messageInput", "I understand her choice a little better now.")
                    click(window, "sendMessageButton")
                    wait_until(lambda: not vm.busy)
                    assert vm.messages[-1]["speechError"]
                    capture("voice-speech-error", width)
                    click(window, "retrySpeech-" + vm.messages[-1]["id"])
                    wait_until(lambda: not vm.busy)
                    states = [entry for entry in captures if entry["width"] == width and entry["view"].startswith("voice-")]
                    for control in ("recordButton", "sendMessageButton"):
                        positions = [entry["windowControls"][control][1] for entry in states]
                        assert max(positions) - min(positions) < 1, (width, control, positions)
                ws.toggleSource()
                wait_until(lambda: ws.documentReady)
                if args.review_fixture:
                    ws.selectSource(20, 20)
                capture("source", width)
                ws.toggleSource()
                ws.navigate("import")
                capture("import", width)
                ws.browseMaterial(material_id)
                ws.openScope()
                wait_until(lambda: ws.documentReady)
                capture("scope", width)
                for category in ("appearance", "learning", "services", "audio", "local", "data"):
                    ws.setCategory(category)
                    ws.navigate("settings")
                    if category == "local":
                        wait_until(lambda: not library.busy)
                    capture("settings-" + category, width)
                ws.setCategory("local")
                ws.navigate("settings")
                click(window, "openSpeechCompute")
                capture("compute", width)
                ws.navigate("queue")
                capture("queue", width)
            ws.openThread(thread_id)
            vm.finishPractice()
            wait_until(lambda: not vm.busy)
            capture("review", window.width())
            ws.navigate("chat")
            capture("history", window.width())
            # Only messages emitted while the owned engine is alive are runtime diagnostics.
            report = {
                "provider": "Mock",
                "visible": args.visible,
                "platform": app.platformName(),
                "scale": os.getenv("QT_SCALE_FACTOR", "system"),
                "theme": args.theme,
                "captures": captures,
                "warnings": list(dict.fromkeys(warnings)),
                "real_ai": False,
                "model_downloads": False,
                "database": "temporary",
                "voice": "QML record/stop/automatic-transcribe-submit/sentence-play with synthetic WAV and test audio transport",
                "voice_states": args.voice_states,
                "synthetic_voice_timings": speech_timings,
                "input": "file URL dropped on QML DropArea; text committed as input-method events",
                "review_fixture": args.review_fixture,
                "intermediate": intermediate,
            }
            (args.output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"Captured {len(captures)} QML views; platform={app.platformName()}, dpr={window.devicePixelRatio()}"
            )
        finally:
            ws.close()
            library.close()
            vm.close()
            window.close()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()
