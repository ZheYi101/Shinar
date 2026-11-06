"""Visible/offscreen continuous QML checks; optional isolated human-device session."""
# ruff: noqa: E402

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import traceback
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from PySide6.QtCore import QSettings, QTimer, qInstallMessageHandler, Qt
from PySide6.QtGui import QGuiApplication, QFontDatabase, QInputMethodEvent
from PySide6.QtTest import QTest

from lingualoop.application import LearningWorkbench
from lingualoop.desktop.app import create_engine
from lingualoop.desktop.preferences import DesktopPreferences
from lingualoop.desktop.speech_library import SpeechLibraryViewModel
from lingualoop.desktop.viewmodel import LearningViewModel
from lingualoop.infrastructure import SQLiteStore
from lingualoop.local_speech.profiles import LocalSpeechProfile
from lingualoop.providers.mock import MockLearningLLMProvider
from validate_ui_workspace import click, visible_item, wait_until


def enter_text(window, name: str, text: str) -> None:
    target = visible_item(window, name)
    window.requestActivate()
    target.forceActiveFocus()
    wait_until(lambda: target.property("activeFocus"), timeout=5)
    QTest.qWait(30)
    previous = target.property("text")
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    wait_until(lambda: target.property("selectedText") == previous, timeout=5)
    event = QInputMethodEvent()
    event.setCommitString(text)
    QGuiApplication.sendEvent(target, event)
    QTest.qWait(50)
    assert target.property("text") == text, (name, "IME commit did not replace the selected text")


class SlowDialogue(MockLearningLLMProvider):
    """Numbered audio samples in human mode; never pretend to understand an answer."""

    def __init__(self, language="en", human=False):
        self.language, self.human, self.hold, self.calls = language, human, False, 0
        self.reply_delay = 1.2 if human else 0
        self.responses = []

    async def stream_reply(self, **kwargs):
        self.calls += 1
        number = self.calls
        if self.human:
            first = {
                "en": f"Voice test, reply {number}. ",
                "zh": f"语音测试，第{number}次回复。",
                "ja": f"音声テスト、{number}回目の返事です。",
            }[self.language]
            samples = {
                "en": (
                    "The train arrives at a small station in the morning.",
                    "A blue umbrella stands beside the door.",
                    "The afternoon sunlight falls across the wooden table.",
                    "Two friends are walking along the river.",
                    "There is a little clock above the ticket window.",
                    "The last bus leaves before the shops close.",
                ),
                "zh": (
                    "清晨，列车停在一个安静的小站。",
                    "门边放着一把蓝色的雨伞。",
                    "午后的阳光照在木桌上。",
                    "两位朋友正沿着河边散步。",
                    "售票窗口上方挂着一个小钟。",
                    "商店关门前，最后一班公交车出发了。",
                ),
                "ja": (
                    "朝の電車が小さな駅に到着しました。",
                    "ドアのそばに青い傘が置いてあります。",
                    "午後の日差しが木のテーブルを照らしています。",
                    "二人の友達が川沿いを歩いています。",
                    "切符売り場の上に小さな時計があります。",
                    "お店が閉まる前に、最後のバスが出発しました。",
                ),
            }[self.language]
            last = samples[(number - 1) % len(samples)]
        else:
            first, last = {
                "en": ("That makes sense. ", "Tell me more."),
                "zh": ("我理解你的意思。", "请继续说吧。"),
                "ja": ("なるほど。", "もう少し教えてください。"),
            }[self.language]
        message = kwargs.get("user_message")
        self.responses.append({"number": number, "user_message_id": getattr(message, "id", None)})
        yield first
        if self.human:
            await asyncio.sleep(self.reply_delay)
        while self.hold:
            await asyncio.sleep(0.02)
        yield last


def main(args, *, before_human=None):
    if not args.visible and not args.human:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = ROOT / "build" / "continuous-voice" / ("desktop-" + uuid4().hex)
    root.mkdir(parents=True)
    output = args.output or root / "captures"
    output.mkdir(parents=True, exist_ok=True)
    warnings = []
    callback_errors = []

    def record_callback_error(error_type, value, tb):
        # No exception bodies: a provider or device exception can contain user data.
        callback_errors.append(
            {
                "type": error_type.__name__,
                "frames": [f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(tb)],
            }
        )

    previous_exception_handler = sys.excepthook
    sys.excepthook = record_callback_error
    qInstallMessageHandler(lambda kind, context, text: warnings.append(text))
    app = QGuiApplication([])
    if os.name == "nt":
        for font in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc", "seguisym.ttf", "seguiemj.ttf"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font)
            )
    language = args.case if args.human else "en"
    provider = SlowDialogue(language, args.human)
    library = SpeechLibraryViewModel(args.speech_cache or root / "speech")
    if args.human:
        if args.profiles:
            cases = json.loads(args.profiles.read_text(encoding="utf-8"))
            case = next(c for c in cases if c["name"] == args.case)
            language = case["language"]
            provider.language = language
            for task in ("stt", "tts"):
                library.local_service.register_prepared(LocalSpeechProfile(**case[task]))
        speech = library.local_service
        audio = None
        stt, tts = speech.provider("stt"), speech.provider("tts")
    else:
        from test_desktop_workflow import FakeAudio, FakeSpeech

        speech, audio = FakeSpeech(), FakeAudio()
        stt = tts = speech
    prefs = DesktopPreferences(QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat))
    prefs.setValue("themeMode", args.theme)
    prefs.setValue("targetLanguage", {"en": "english", "ja": "japanese", "zh": "chinese"}[language])
    vm = LearningViewModel(
        LearningWorkbench(provider, event_store=SQLiteStore(root / "learning.sqlite3")),
        "Mock · isolated continuous voice",
        preferences=prefs,
        stt_provider=stt,
        tts_provider=tts,
        audio_controller=audio,
    )
    engine = create_engine(
        vm,
        speech_library=library,
        window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat),
    )
    window, ws = engine.rootObjects()[0], engine.workspace
    window.setTitle("LinguaLoop · 连续语音独立验收 · Mock v2 · 音频修复版")
    window.showNormal()
    window.setPosition(16, 16)
    window.setWidth(1180)
    window.setHeight(900)
    window.raise_()
    window.requestActivate()
    if args.visible or args.human:
        assert QTest.qWaitForWindowExposed(window)
    window.grabWindow()
    call = vm.voice.call
    call.root = args.runtime_root.resolve()
    if not args.human:
        from test_desktop_continuous_voice import SyntheticBridge, SyntheticRtc

        call.bridge_factory, call.process_factory = SyntheticBridge, SyntheticRtc
    captures = []
    report = {
        "human_mode": args.human,
        "real_devices": args.human,
        "real_local_models": args.human,
        "real_rtc": args.human,
        "paid_model_calls": 0,
        "selection_mode": "normal_settings"
        if args.speech_cache
        else "explicit_prepared_profile"
        if args.human
        else "mock",
        "mock_reply_mode": "numbered_scripted_samples" if args.human else "short_synthetic_fixture",
        "visible": args.visible or args.human,
        "qt_platform": app.platformName(),
        "qt_scale_factor": os.getenv("QT_SCALE_FACTOR", "system"),
        "theme": args.theme,
        "human_acceptance_completed": False,
        "captures": captures,
        "callback_errors": callback_errors,
    }

    def capture(label, width):
        if args.visible:
            window.showNormal()
            window.setPosition(16, 16)
            window.raise_()
            window.requestActivate()
            assert QTest.qWaitForWindowExposed(window, 5000)
        window.setWidth(width)
        QTest.qWait(100)
        window.grabWindow()
        from PySide6.QtCore import QPointF

        def settled():
            window.grabWindow()
            button = visible_item(window, "windowCloseButton")
            point = button.mapToScene(QPointF())
            return point.x() + button.width() <= window.width() + 1

        try:
            wait_until(settled, timeout=5)
        except RuntimeError:
            control = visible_item(window, "continuousVoiceButton")
            chain = []
            while control is not None:
                chain.append(
                    [control.metaObject().className(), control.width(), control.implicitWidth()]
                )
                control = control.parentItem()
            print(
                json.dumps(
                    {
                        "layout_failure": chain,
                        "window_width": window.width(),
                        "content_width": window.contentItem().width(),
                    }
                ),
                flush=True,
            )
            raise
        path = output / f"{width}-{label}.png"
        assert window.grabWindow().save(str(path))
        for name in (
            "continuousVoiceButton",
            "muteMicrophoneButton",
            "stopReplyButton",
            "sendMessageButton",
            "openMicrophoneSettingsButton",
        ):
            try:
                control = visible_item(window, name)
            except AssertionError:
                continue
            corner = control.mapToScene(QPointF())
            assert corner.x() >= 0 and corner.y() >= 0
            assert corner.x() + control.width() <= window.width() + 1
            assert corner.y() + control.height() <= window.height() + 1
        captures.append(
            {
                "width": width,
                "state": label,
                "image": str(path),
                "connection": call.connectionState,
                "input": call.inputState,
                "reply": call.replyState,
                "output": call.outputState,
                "muted": call.muted,
            }
        )

    try:
        # Actual paste/import/range/start UI; no database history injection.
        ws.navigate("import")
        click(window, "pasteImportTab")
        enter_text(window, "importTitleInput", "连续语音验收 · 独立测试库")
        enter_text(
            window,
            "importTextInput",
            "Mira returned to the station. Ren had waited beside the clock. She changed her mind and stayed.",
        )
        click(window, "commitImportButton")
        wait_until(lambda: not vm.busy and ws.documentReady)
        click(window, "readWholeMaterialButton")
        click(window, "saveScopeButton")
        wait_until(lambda: not vm.busy)
        ws.newThreadPage()
        click(window, "startDiscussionButton")
        wait_until(lambda: vm.sessionActive and not vm.busy)
        if args.human:
            if before_human:
                report["pre_human_check"] = before_human(vm, window, ws, library, provider)
                report["automated_baseline_calls"] = provider.calls
            print(
                json.dumps(
                    {
                        "human_window_ready": True,
                        "test_database": str(root / "learning.sqlite3"),
                        "report": str(root / "report.json"),
                        "microphone_open": False,
                    }
                ),
                flush=True,
            )
            timeline = []
            last = None

            def observe():
                nonlocal last
                state = (
                    call.connectionState,
                    call.inputState,
                    call.replyState,
                    call.outputState,
                    call.muted,
                    len(vm.messages),
                    len(callback_errors),
                    call.faults[-1]["at"] if call.faults else None,
                )
                if state != last:
                    timeline.append(
                        {"at": monotonic(), "state": state, "timings": dict(call.timings)}
                    )
                    last = state
                    report.update(
                        timeline=timeline,
                        mock_dialogue_calls=provider.calls,
                        mock_responses=list(provider.responses),
                        confirmed_users=sum(m["role"] == "user" for m in vm.messages),
                        voice_faults=list(call.faults),
                    )
                    (root / "report.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                    )

            timer = QTimer()
            timer.setInterval(100)
            timer.timeout.connect(observe)
            timer.start()
            app.exec()
            timer.stop()
        else:
            from test_desktop_workflow import pcm_wav

            for width in [int(n) for n in args.widths.split(",")]:
                window.setWidth(width)
                click(window, "continuousVoiceButton")
                wait_until(lambda: call.connectionState == "active" and not call.muted)
                capture("listening", width)
                enter_text(window, "messageInput", "这是下一轮独立草稿。日本語の長い文章 😀 " * 3)
                click(window, "muteMicrophoneButton")
                capture("muted-draft", width)
                click(window, "muteMicrophoneButton")
                wait_until(lambda: not call.muted)
                gate = False

                async def transcribe(data):
                    while not gate:
                        await asyncio.sleep(0.02)
                    return "I think she changed her mind."

                speech.transcribe = transcribe
                provider.hold = True
                call.process.event("input_started", utterance="one", revision=1)
                QTest.qWait(30)
                call.process.event("utterance", pcm_wav(), utterance="one", revision=1)
                wait_until(lambda: call.inputState == "recognizing")
                capture("recognizing", width)
                gate = True
                wait_until(
                    lambda: call.outputState == "playing" and call.replyState == "generating"
                )
                capture("reply-and-play", width)
                call.process.event("input_started", utterance="two", revision=1)
                QTest.qWait(100)
                provider.hold = False
                call.process.event("utterance", pcm_wav(), utterance="two", revision=1)
                wait_until(
                    lambda: (
                        call.outputState == "idle"
                        and call.replyState == "idle"
                        and vm.messages[-1]["role"] == "assistant"
                    )
                )
                capture("interrupted-history", width)

                async def fail(data):
                    raise RuntimeError("synthetic_recognition_failure")

                speech.transcribe = fail
                call.process.event("input_started", utterance="failed", revision=1)
                QTest.qWait(30)
                call.process.event("utterance", pcm_wav(), utterance="failed", revision=1)
                wait_until(lambda: call.canRetryInput)
                capture("recognition-failed", width)
                call.bridge.fault.emit("microphone_failed")
                capture("microphone-unavailable", width)
                click(window, "continuousVoiceButton")
                wait_until(lambda: not vm.busy)
            assert not callback_errors, callback_errors
            report["passed"] = True
    finally:
        vm.close()
        library.close()
        ws.close()
        report["mock_dialogue_calls"] = provider.calls
        report["qml_warnings"] = [
            w
            for w in warnings
            if any(
                s in w.lower()
                for s in (
                    "referenceerror",
                    "typeerror",
                    "binding loop",
                    "cannot assign",
                    "failed to load",
                )
            )
        ]
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "report": str(root / "report.json"),
                    "captures": len(captures),
                    "qml_errors": len(report["qml_warnings"]),
                }
            ),
            flush=True,
        )
        window.close()
        sys.excepthook = previous_exception_handler
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--speech-cache", type=Path)
    parser.add_argument("--case", default="ja")
    parser.add_argument(
        "--runtime-root", type=Path, default=ROOT / "build/continuous-voice/runtime"
    )
    parser.add_argument("--widths", default="360,600,800,1180,1440")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.human and not (args.profiles or args.speech_cache):
        parser.error(
            "--human requires --speech-cache or prepared --profiles; no models are downloaded"
        )
    if args.profiles and args.speech_cache:
        parser.error("Choose either normal settings or explicit prepared profiles")
    raise SystemExit(main(args))
