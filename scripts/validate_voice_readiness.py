"""Isolated visible QML preflight and optional real local TTS/RTC continuity check."""
# ruff: noqa: E402

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from threading import Event
from time import monotonic, sleep
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]
os.environ["RUN_REAL_AI_TESTS"] = "0"
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QSettings, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.speech_library import SpeechLibraryViewModel
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers.mock import MockLearningLLMProvider
from test_desktop_workflow import FakeAudio, FakeSpeech, click, item, load_and_start
import test_desktop_workflow as workflow
from test_voice_readiness import Probe
from validate_voice_handoff import TestInputBridge


def wait(predicate, timeout=180):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        sleep(0.005)
    assert predicate(), "Voice readiness/continuity check timed out"


def main(args):
    # Real cold model loads exceed the offline fixture's five-second deadline.
    workflow.until = lambda predicate, timeout=5000: wait(predicate, max(180, timeout / 1000))
    root = ROOT / "build/voice-readiness" / uuid4().hex
    root.mkdir(parents=True)
    warnings, callbacks, captures = [], [], []
    qInstallMessageHandler(lambda kind, context, text: warnings.append(text))
    previous = sys.excepthook
    sys.excepthook = lambda kind, value, tb: callbacks.append({
        "type": kind.__name__,
        "frames": [f"{frame.name}:{frame.lineno}" for frame in traceback.extract_tb(tb)],
    })
    app = QGuiApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
    first_pcm = Event()

    class Dialogue(MockLearningLLMProvider):
        calls = 0
        text_completed_at = None

        async def stream_reply(self, **kwargs):
            self.calls += 1
            yield "朝の電車が小さな駅に到着しました。"
            while not first_pcm.is_set():
                await asyncio.sleep(0.01)
            yield "ドアのそばには青い傘が置いてあります。"
            await asyncio.sleep(0.05)
            yield "二人の友達が川沿いをゆっくり歩いています。"
            self.text_completed_at = monotonic()

    prefs = DesktopPreferences(QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat))
    prefs.setValue("themeMode", "light")
    speech, provider = FakeSpeech(), Dialogue()
    vm = LearningViewModel(
        LearningWorkbench(provider, event_store=SQLiteStore(root / "test.sqlite3")),
        "Mock · 语音准备与连续播放检查", preferences=prefs,
        stt_provider=speech, tts_provider=speech,
        audio_controller=None if args.speech_cache else FakeAudio(),
    )
    readiness, call = vm.voice.preflight, vm.voice.call
    if not args.microphone:
        readiness.probe_factory = Probe
    if args.runtime_root:
        call.root = args.runtime_root.resolve()
    library = SpeechLibraryViewModel(args.speech_cache or root / "speech")
    engine = create_engine(
        vm, speech_library=library,
        window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat),
    )
    window, ws = engine.rootObjects()[0], engine.workspace
    window.setTitle("Shinar · 语音预检查与播放 · 独立 Mock 验证")
    window.setWidth(1180)
    window.setHeight(900)
    window.showNormal()
    assert QTest.qWaitForWindowExposed(window)
    report = {
        "native_qml": app.platformName() != "offscreen", "scale": os.getenv("QT_SCALE_FACTOR", "1"),
        "physical_microphone_diagnostic": args.microphone,
        "diagnostic_audio_saved_or_transcribed": False, "paid_model_calls": 0,
        "real_models": bool(args.speech_cache), "captures": captures,
        "human_listening_acceptance": False,
    }
    try:
        load_and_start(vm, window)
        wait(lambda: not readiness.busy and not vm.busy)
        report.update(preflight=list(readiness.checks), preflight_ms=dict(readiness.timings))
        assert not call.active and call.process is None
        assert readiness._probe is None
        if args.speech_cache:
            assert all(row["state"] == "ready" for row in readiness.checks), readiness.checks
        original = dict(readiness._states)
        for theme in ("light", "dark"):
            prefs.setValue("themeMode", theme)
            for state in ("prepared", "loading", "needs_setup"):
                readiness._states = dict(original)
                readiness._errors = {}
                if state == "loading":
                    readiness._states.update(stt="loading", tts="loading")
                elif state == "needs_setup":
                    readiness._states.update(stt="error", microphone="error")
                    readiness._errors["stt"] = "识别模型尚未准备，请在本地语音模型中准备并选用。"
                readiness.changed.emit()
                for width in (360, 600, 800, 1180, 1440):
                    window.setWidth(width)
                    QTest.qWait(100)
                    for name in ("continuousVoiceButton", "retryVoiceReadiness", "sendMessageButton"):
                        target = item(window, name)
                        p = target.mapToScene(QPointF())
                        assert 0 <= p.x() and p.x() + target.width() <= window.width() + 1
                        assert 0 <= p.y() and p.y() + target.height() <= window.height() + 1
                    path = root / f"{theme}-{state}-{width}.png"
                    assert window.grabWindow().save(str(path))
                    captures.append(str(path))
        readiness._states, readiness._errors = original, {}
        readiness.changed.emit()
        prefs.setValue("themeMode", "light")
        window.setWidth(1180)
        if args.speech_cache:
            assert args.runtime_root, "Real continuity check requires prepared RTC assets"
            bridge = TestInputBridge(vm._audio, call)
            submitted_until = first_write = None
            gaps = []

            def rendered(header, data):
                nonlocal submitted_until, first_write
                now = monotonic()
                first_write = first_write or now
                if submitted_until is not None and now > submitted_until:
                    gaps.append((now - submitted_until) * 1000)
                submitted_until = max(submitted_until or now, now) + len(data) / (
                    bridge.output_spec.rate * bridge.output_spec.frame_bytes
                )
                first_pcm.set()

            bridge.rendered.connect(rendered)
            call.bridge_factory = lambda: bridge
            click(window, "continuousVoiceButton")
            wait(lambda: call.connectionState in {"active", "failed"})
            assert call.connectionState == "active", call.errorText
            wait(lambda: not call.muted)
            submissions = []
            request = call.process.request

            async def timed_request(kind, *a, **kw):
                if kind != "segment":
                    return await request(kind, *a, **kw)
                started = monotonic()
                result = await request(kind, *a, **kw)
                submissions.append({"index": kw["index"], "start": started, "end": monotonic()})
                return result

            def submission_gaps():
                return [(b["start"] - a["end"]) * 1000 for a, b in zip(submissions, submissions[1:])]

            call.process.request = timed_request
            click(window, "muteMicrophoneButton")
            wait(lambda: call.canSendText)
            vm.draft = "Please describe the scene."
            click(window, "sendMessageButton")
            wait(lambda: provider.calls == 1 and call.replyState == "idle" and call.outputState == "idle")
            assert bridge.input_io is None  # RTC input is synthetic silence throughout.
            report.update(
                real_rtc=True, real_output_device=True, reply_ms=dict(call.timings),
                playback_software_gaps_ms=[g for g in gaps if g > 10],
                inter_segment_submission_gaps_ms=submission_gaps(),
                first_pcm_before_complete_text=bool(first_write and first_write < provider.text_completed_at),
                voice_faults=list(call.faults), mock_dialogue_calls=provider.calls,
                output_bytes=bridge._written,
            )
            assert report["first_pcm_before_complete_text"] and not call.faults
            assert not [g for g in gaps if g > 100], gaps
            if args.compare_serial:
                # Emulate the old await-send-then-synthesize scheduling. The
                # models, RTC, sink and phrase buffering are otherwise identical.
                gate = asyncio.Event()
                gate.set()
                service = library.local_service
                original_provider = service.provider

                class SerializedTTS:
                    def __init__(self, backend):
                        self.backend = backend

                    def __getattr__(self, name):
                        return getattr(self.backend, name)

                    async def bind(self, language):
                        return SerializedTTS(await self.backend.bind(language))

                    async def synthesize(self, text):
                        await gate.wait()
                        gate.clear()
                        return await self.backend.synthesize(text)

                async def serial_request(kind, *a, **kw):
                    result = await timed_request(kind, *a, **kw)
                    if kind == "segment":
                        gate.set()
                    return result

                service.provider = lambda task: (
                    SerializedTTS(original_provider(task)) if task == "tts" else original_provider(task)
                )
                call.process.request = serial_request
                try:
                    submissions.clear()
                    first_pcm.clear()
                    submitted_until = first_write = None
                    gaps.clear()
                    vm.draft = "Please describe the same scene again."
                    click(window, "sendMessageButton")
                    wait(lambda: provider.calls == 2 and call.replyState == "idle" and call.outputState == "idle")
                    report["serialized_comparison"] = {
                        "inter_segment_submission_gaps_ms": submission_gaps(),
                        "reply_ms": dict(call.timings), "emulated_previous_scheduling": True,
                    }
                    report["mock_dialogue_calls"] = provider.calls
                    assert not call.faults
                finally:
                    service.provider = original_provider
                    call.process.request = request
            click(window, "continuousVoiceButton")
            wait(lambda: not vm.busy and not readiness.busy)
        report["qml_errors"] = [w for w in warnings if any(s in w for s in ("ReferenceError", "TypeError", "Binding loop", "Cannot assign"))]
        report["callback_errors"] = callbacks
        assert not report["qml_errors"] and not callbacks
        report["passed"] = True
    finally:
        report.setdefault("preflight", list(readiness.checks))
        report.setdefault("preflight_ms", dict(readiness.timings))
        vm.close()
        window.close()
        ws.close()
        engine.deleteLater()
        app.processEvents()
        sys.excepthook = previous
        path = root / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(path), "passed": report.get("passed", False)}), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech-cache", type=Path, help="Selected normal local models; no installation")
    parser.add_argument("--runtime-root", type=Path, help="Already prepared RTC/APM, Silero and SFU")
    parser.add_argument("--microphone", action="store_true", help="Brief real microphone diagnostic; discard all PCM")
    parser.add_argument("--compare-serial", action="store_true", help="Compare the previous serialized synthesis/send scheduling")
    raise SystemExit(main(parser.parse_args()))
