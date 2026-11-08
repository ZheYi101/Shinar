"""Visible QML + real RTC/sink, synthetic silent input. Never opens a microphone."""
# ruff: noqa: E402

import argparse
import asyncio
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import sys
from time import monotonic, sleep
from uuid import uuid4
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
os.environ.setdefault("SHINAR_KIRIGAMI_MODE", "off")

from PySide6.QtCore import QSettings, QTimer, QObject, Signal, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.voice.pcm_audio import PcmAudioBridge
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.voice.routing import SpeechRoute
from shinar.infrastructure import SQLiteStore
from shinar.local_speech.installation import managed_status
from shinar.providers.mock import MockLearningLLMProvider
from shinar.realtime.audio_process import AudioSessionProcess
from shinar.realtime.continuous_assets import vad_path
from validate_continuous_desktop import enter_text
from validate_ui_workspace import click, wait_until


class ProbeEvents(QObject):
    received = Signal(str)
    transport = Signal(object, bytes)


def main(args):
    app = QGuiApplication([])
    assert app.platformName() != "offscreen", "This probe requires a native visible window."
    output = ROOT / "build/continuous-voice" / ("playback-" + uuid4().hex)
    output.mkdir(parents=True)
    prefs = DesktopPreferences(QSettings(str(output / "prefs.ini"), QSettings.Format.IniFormat))
    prefs.setValue("targetLanguage", "japanese")
    library = SpeechLibraryViewModel(args.speech_cache) if args.speech_cache else None
    vm = LearningViewModel(
        LearningWorkbench(
            MockLearningLLMProvider(), event_store=SQLiteStore(output / "test.sqlite3")
        ),
        "Mock · 合成音频播放检查 · 不开麦",
        preferences=prefs,
    )
    engine = create_engine(
        vm,
        speech_library=library,
        window_settings=QSettings(str(output / "window.ini"), QSettings.Format.IniFormat),
    )
    window, ws, call = engine.rootObjects()[0], engine.workspace, vm.voice.call
    window.setTitle("Shinar · 合成音频检查 · 不开麦")
    window.setWidth(1180)
    window.setHeight(900)
    window.showNormal()
    assert QTest.qWaitForWindowExposed(window)
    call.root = args.runtime_root.resolve()
    report = {
        "native_qml": True,
        "real_rtc": True,
        "real_output_device": True,
        "microphone_open": False,
        "input": "synthetic_silence",
        "output": "synthetic_silence",
        "real_stt": False,
        "real_tts": bool(library),
        "human_acceptance": False,
        "paid_model_calls": 0,
        "legacy_refresh_replay": args.legacy_refresh,
        "playback_frames": 0,
    }
    events = ProbeEvents()
    capture = QTimer()
    done = drained = False
    max_event_gap = 0
    bridge = process = None
    errors = []
    faults = []

    def delivered(generation):
        nonlocal drained
        drained = True

    def stage(kind):
        nonlocal done
        if kind == "capture":
            capture.start(10)
        elif kind == "begin":
            bridge.begin_output("1")
        elif kind == "done":
            capture.stop()
            done = True
        elif kind == "closing":
            capture.stop()

    events.received.connect(stage, Qt.ConnectionType.QueuedConnection)
    try:
        ws.navigate("import")
        click(window, "pasteImportTab")
        enter_text(window, "importTitleInput", "合成音频设备检查")
        enter_text(window, "importTextInput", "Two friends met at a small station in the morning.")
        click(window, "commitImportButton")
        wait_until(lambda: not vm.busy and ws.documentReady)
        click(window, "readWholeMaterialButton")
        click(window, "saveScopeButton")
        wait_until(lambda: not vm.busy)
        ws.newThreadPage()
        click(window, "startDiscussionButton")
        wait_until(lambda: vm.sessionActive and not vm.busy)
        # This device diagnostic owns its transport directly; it never fabricates
        # a conversation or writes the production call coordinator's state.
        bridge = PcmAudioBridge(vm.audio, window)
        assert isinstance(bridge, PcmAudioBridge)
        config = bridge.formats()
        config.update(cache=str(call.root / "sfu"), vad=str(vad_path(call.root)), pause_ms=650)
        call.bridge = bridge
        bridge.open()  # QAudioSource is constructed, but resume()/start() is NEVER called.
        bridge.drained.connect(delivered)
        identity = uuid4().hex

        def transport(header, payload):
            if header["kind"] == "playback":
                bridge.enqueue(header["generation"], payload)
            elif header["kind"] == "output_drained":
                bridge.finish_output(header["generation"])

        events.transport.connect(transport, Qt.ConnectionType.QueuedConnection)
        bridge.fault.connect(faults.append)

        def receive(header, payload):
            if header["kind"] == "playback":
                report["playback_frames"] += 1
            events.transport.emit(header, payload)
            if args.legacy_refresh and header["kind"] == "playback":
                # Reproduce the old shared-notify binding load on the GUI thread.
                events.received.emit("legacy")

        def legacy(kind):
            if kind == "legacy":
                call.componentsChanged.emit()
                call.changed.emit()

        events.received.connect(legacy)
        process = AudioSessionProcess(
            identity, receive, python=managed_status(call.root, "rtc-cpu")["python"]
        )
        call.process = process
        route = SpeechRoute(vm, "tts")
        sample = b"\x80" if bridge.input_spec.sample == "uint8" else b"\0"
        silent_frame = sample * (bridge.input_spec.rate // 100 * bridge.input_spec.frame_bytes)
        capture.timeout.connect(
            lambda: call.post(lambda: process.send(
                "capture", silent_frame, captured_at=monotonic(), capture_delay_ms=10
            ))
        )
        bridge.rendered.connect(lambda header, data: call.post(lambda: process.send("rendered", data, **header)))
        bridge.credit.connect(lambda: call.post(lambda: process.send("credit")))

        async def run():
            try:
                report["connection"] = await process.start(config)
                report["input_format"] = asdict(bridge.input_spec)
                report["output_format"] = asdict(bridge.output_spec)
                await process.request("resume")
                events.received.emit("capture")
                events.received.emit("begin")
                await process.request("output_begin", generation="1", turn="probe")
                tts = await route.bind("ja") if library else None
                report["synthesis_ms"] = []
                for index in range(3):
                    if tts:
                        started = monotonic()
                        audio = await tts.synthesize(
                            (
                                "音声テスト、一回目の返事です。",
                                "朝の電車が小さな駅に到着しました。",
                                "これで三つの音声の再生を確認しました。",
                            )[index]
                        )
                        report["synthesis_ms"].append((monotonic() - started) * 1000)
                    else:
                        stream = io.BytesIO()
                        with wave.open(stream, "wb") as wav:
                            wav.setnchannels(1)
                            wav.setsampwidth(2)
                            wav.setframerate(24000)
                            wav.writeframes(b"\0\0" * (24000 * 3))
                        audio = stream.getvalue()
                    await process.request("segment", audio, generation="1", index=index)
                    await asyncio.sleep(0.3)
                await process.request("output_done", timeout=30)
                deadline = monotonic() + 15
                while not drained and monotonic() < deadline and not faults:
                    await asyncio.sleep(0.02)
                report["stats"] = await process.request("stats")
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                events.received.emit("closing")
                await asyncio.sleep(0.05)
                closing = monotonic()
                await process.close()
                report["cleanup_ms"] = (monotonic() - closing) * 1000
                events.received.emit("done")

        call.post(run)
        deadline, previous = monotonic() + 90, monotonic()
        while not done and monotonic() < deadline:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            now = monotonic()
            max_event_gap = max(max_event_gap, now - previous)
            previous = now
            sleep(0.005)
        report.update(
            drained=drained,
            voice_faults=faults,
            max_event_gap_ms=max_event_gap * 1000,
            written_bytes=bridge._written,
            callback_errors=errors,
        )
        if library:
            report["output"] = "normal_settings_local_tts"
        report["passed"] = bool(done and drained and not faults and not errors)
        assert bridge.input_io is None, "Probe must never open the physical microphone."
        window.grabWindow().save(str(output / "playback.png"))
    finally:
        capture.stop()
        vm.close()
        window.close()
        ws.close()
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(output / "report.json"), **report}), flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--legacy-refresh", action="store_true")
    parser.add_argument(
        "--speech-cache", type=Path, help="Optional normal settings cache for real Japanese TTS."
    )
    raise SystemExit(main(parser.parse_args()))
