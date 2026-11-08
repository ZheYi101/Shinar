"""Self-test real QML/STT/TTS/RTC and duplex devices before leaving a human window."""
# ruff: noqa: E402

import argparse
import asyncio
from array import array
from collections import deque
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from types import SimpleNamespace
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from PySide6.QtCore import QCoreApplication, QEvent, QMicrophonePermission, QTimer, Qt

from shinar.desktop.pcm_audio import PcmAudioBridge
from shinar.desktop.voice import _SpeechRoute
from shinar.realtime.pcm import DeviceFormat, PcmConverter
import validate_continuous_desktop as desktop_check
from validate_ui_workspace import click


def wait_until(predicate, timeout=30):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        sleep(0.01)  # QTest.qWait keeps the GIL and starves the inference/RTC worker.
    assert predicate(), "Voice self-test timed out."


class TestInputBridge(PcmAudioBridge):
    """Only capture is synthetic. The real selected sink and RTC remain in use."""

    def __init__(self, audio, parent):
        super().__init__(audio, parent)
        self.pending = deque()
        self.feed_timer = QTimer(self)
        self.feed_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.feed_timer.setInterval(10)
        self.feed_timer.timeout.connect(self._feed)
        self.played_blocks = 0

    def resume(self):
        self.feed_timer.start()
        self.started.emit()

    def mute(self):
        self.feed_timer.stop()
        self.pending.clear()
        super().mute()

    def supply(self, pcm: bytes) -> None:
        assert not self.pending, "Wait for the preceding test utterance to finish."
        size = self.input_spec.rate // 100 * self.input_spec.frame_bytes
        self.pending.extend(pcm[i : i + size] for i in range(0, len(pcm), size))

    def _feed(self):
        size = self.input_spec.rate // 100 * self.input_spec.frame_bytes
        silence = (b"\x80" if self.input_spec.sample == "uint8" else b"\0") * size
        data = self.pending.popleft().ljust(size, silence[:1]) if self.pending else silence
        self.capture.emit({"captured_at": monotonic(), "capture_delay_ms": 10}, data)

    def enqueue(self, generation, payload):
        if generation == self.generation:
            self.played_blocks += 1
        super().enqueue(generation, payload)


def on_worker(call, operation, timeout=180):
    result = {}

    async def run():
        try:
            result["value"] = await operation()
        except Exception as error:
            result["error_type"] = type(error).__name__
        finally:
            result["done"] = True

    call.post(run)
    wait_until(lambda: result.get("done"), timeout=timeout)
    assert "error_type" not in result, result.get("error_type")
    return result.get("value")


def convert_wav(audio: bytes, target: DeviceFormat) -> bytes:
    from livekit import rtc

    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getsampwidth() == 2 and wav.getcomptype() == "NONE"
        source = DeviceFormat(wav.getframerate(), wav.getnchannels(), "int16")
        converter = PcmConverter(source, target, rtc)
        return converter.push(wav.readframes(wav.getnframes())) + converter.flush()


def duplex_probe(vm, audio: bytes, report) -> None:
    """Physical mic samples stay here, never enter STT/RTC or a learning database."""
    assert (
        QCoreApplication.instance().checkPermission(QMicrophonePermission())
        == Qt.PermissionStatus.Granted
    )
    bridge = PcmAudioBridge(vm._audio)
    faults, drained = [], []
    stats = {"capture_blocks": 0, "capture_bytes": 0, "peak_pcm16": 0, "max_capture_gap_ms": 0}
    last_capture = None

    def capture(header, data):
        nonlocal last_capture
        now = monotonic()
        if last_capture is not None:
            stats["max_capture_gap_ms"] = max(
                stats["max_capture_gap_ms"], (now - last_capture) * 1000
            )
        last_capture = now
        stats["capture_blocks"] += 1
        stats["capture_bytes"] += len(data)
        if bridge.input_spec.sample == "int16":
            stats["peak_pcm16"] = max(
                stats["peak_pcm16"], max(map(abs, array("h", data)), default=0)
            )

    bridge.capture.connect(capture)
    bridge.fault.connect(faults.append)
    bridge.drained.connect(drained.append)
    timer = QTimer()
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    timer.setInterval(10)
    try:
        bridge.formats()
        pcm = on_worker(vm.voice.call, lambda: convert_async(audio, bridge.output_spec))
        size = bridge.output_spec.rate // 100 * bridge.output_spec.frame_bytes
        pending = deque(pcm[i : i + size] for i in range(0, len(pcm), size))

        def play():
            if pending:
                bridge.enqueue("duplex", pending.popleft())
            else:
                timer.stop()
                bridge.finish_output("duplex")

        timer.timeout.connect(play)
        bridge.open()
        bridge.resume()
        bridge.begin_output("duplex")
        timer.start()
        started = monotonic()
        wait_until(lambda: (drained and monotonic() - started >= 5) or faults, timeout=30)
        stats.update(
            duration_ms=(monotonic() - started) * 1000,
            input_format=asdict(bridge.input_spec),
            output_format=asdict(bridge.output_spec),
            input_device=bridge.input_device.description(),
            output_device=bridge.output_device.description(),
            faults=faults,
            playback_drained=bool(drained),
            written_bytes=bridge._written,
            recording_saved=False,
            transcription_performed=False,
        )
        report["physical_duplex"] = stats
        assert not faults and drained and stats["capture_blocks"] >= 20, stats
        assert stats["capture_bytes"] >= bridge.input_format.bytesForDuration(2000000), stats
    finally:
        timer.stop()
        bridge.close()
        bridge.deleteLater()


async def convert_async(audio, target):
    return convert_wav(audio, target)


def self_test(vm, window, ws, library, provider, report):
    call = vm.voice.call
    provider.reply_delay = 4
    window.setTitle("Shinar · 正在自测语音 · 请稍候")
    report.update(
        real_qml=True,
        real_stt=True,
        real_tts=True,
        real_rtc=True,
        real_output_device=True,
        conversation_capture="synthetic_pcm",
        human_acceptance=False,
        paid_model_calls=0,
    )

    def stage(value):
        report["stage"] = value
        print(json.dumps({"self_test_stage": value}), flush=True)

    stage("prepare_test_audio")
    probe = PcmAudioBridge(vm._audio)
    probe.formats()
    input_spec = probe.input_spec
    probe.deleteLater()
    route = _SpeechRoute(vm, "tts")

    async def prepare():
        backend = await route.bind("ja")
        return [
            await backend.synthesize(text)
            for text in (
                "昨日は友達と公園に行きました。",
                "私は青い傘を持って駅で待っています。",
                "明日の朝にもう一度話しましょう。",
            )
        ]

    clips = on_worker(call, prepare)
    pcm = on_worker(call, lambda: converted_clips(clips, input_spec))
    call.bridge_factory = lambda: TestInputBridge(vm._audio, call)
    draft = "自测中的独立文字草稿，语音不能覆盖。"
    desktop_check.enter_text(window, "messageInput", draft)
    stage("start_continuous_voice")
    click(window, "continuousVoiceButton")
    wait_until(
        lambda: (
            call.connectionState == "active"
            and not call.muted
            or call.connectionState in {"off", "failed"}
            or call.errorText
        ),
        timeout=90,
    )
    assert call.connectionState == "active" and not call.muted and not call.errorText
    assert isinstance(call.bridge, TestInputBridge) and call.bridge.input_io is None
    turns = []
    report["turns"] = turns
    for index, clip in enumerate(pcm):
        stage(f"automatic_turn_{index + 1}")
        before = sum(m["role"] == "user" for m in vm.messages)
        frames = call.bridge.played_blocks
        call.bridge.supply(clip)
        wait_until(
            lambda: (
                (
                    sum(m["role"] == "user" for m in vm.messages) == before + 1
                    and vm.messages[-1]["role"] == "assistant"
                    and call.replyState == "idle"
                    and call.outputState == "idle"
                    and call.bridge.played_blocks > frames
                )
                or call.faults
                or call.canRetryInput
            ),
            timeout=180,
        )
        assert not call.faults and not call.canRetryInput, list(call.faults)
        assert vm.draft == draft
        turn_id = vm.messages[-1]["turnId"]
        wait_until(
            lambda: vm._workbench.get_turn(turn_id).speech_delivery == "completed", timeout=10
        )
        turn = vm._workbench.get_turn(turn_id)
        assert turn.state == "completed" and turn.speech_delivery == "completed"
        turns.append(
            {
                "state": turn.state,
                "speech_delivery": turn.speech_delivery,
                "playback_blocks": call.bridge.played_blocks - frames,
                "timings": dict(call.timings),
            }
        )
        print(json.dumps({"automatic_turn_passed": index + 1}), flush=True)
    report["draft_preserved"] = vm.draft == draft

    stage("stop_and_retry_reading")
    click(window, "muteMicrophoneButton")
    wait_until(lambda: call.canSendText)
    calls = provider.calls
    click(window, "speakReplyButton")
    wait_until(lambda: call.outputState == "playing" or call.faults, timeout=120)
    assert not call.faults
    click(window, "stopSpeechButton")
    wait_until(lambda: call.outputState == "idle")
    assert not call._audio_generation and not call.bridge.generation
    assert provider.calls == calls
    report["reading_retry_added_llm_calls"] = provider.calls - calls
    click(window, "continuousVoiceButton")
    wait_until(lambda: not vm.busy, timeout=45)
    call.bridge_factory = None

    stage("physical_microphone_and_headphone")
    window.setTitle("Shinar · 正在检查耳机与麦克风 · 不保存录音")
    duplex_probe(vm, clips[0], report)
    assert not call.faults, list(call.faults)
    report["voice_faults"] = list(call.faults)

    stage("prepare_human_thread")
    provider.reply_delay = 1.2
    ws.newThreadPage()
    click(window, "startDiscussionButton")
    wait_until(lambda: vm.sessionActive and not vm.busy, timeout=120)
    assert call.connectionState == "off" and call.muted
    window.setTitle("Shinar · 可以复测 · Reazon＋VOICEVOX · Mock 对话")
    window.raise_()
    window.requestActivate()
    report.update(passed=True, handoff_ready=True, microphone_open=False)
    window.grabWindow().save(str(Path(vm._workbench._event_store.path).parent / "handoff.png"))


async def converted_clips(clips, target):
    return [convert_wav(audio, target) for audio in clips]


def main(args):
    outcome = {}

    def before_human(vm, window, ws, library, provider):
        report = {}
        path = Path(vm._workbench._event_store.path).parent / "self-test.json"
        last_connection = None

        def connection():
            nonlocal last_connection
            state = vm.voice.call.connectionState
            if state != last_connection:
                print(json.dumps({"self_test_connection": state}), flush=True)
                last_connection = state

        vm.voice.call.changed.connect(connection)
        diagnostics = QTimer()
        diagnostics.setInterval(15000)

        async def stacks():
            chains = []
            for task in asyncio.all_tasks():
                cursor, chain = task.get_coro(), []
                for _ in range(20):
                    frame = getattr(cursor, "cr_frame", None)
                    if frame:
                        chain.append([frame.f_code.co_name, frame.f_lineno])
                    cursor = getattr(cursor, "cr_await", None)
                    if cursor is None:
                        break
                chains.append(chain)
            print(json.dumps({"worker_waits": chains}), flush=True)

        diagnostics.timeout.connect(lambda: vm.voice.call.post(stacks))
        diagnostics.start()
        try:
            self_test(vm, window, ws, library, provider, report)
        except Exception as error:
            report.update(
                passed=False,
                handoff_ready=False,
                error_type=type(error).__name__,
                voice_faults=list(vm.voice.call.faults),
            )
            raise
        finally:
            diagnostics.stop()
            vm.voice.call.changed.disconnect(connection)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            outcome["passed"] = report.get("passed", False)
            print(
                json.dumps(
                    {
                        "self_test_report": str(path),
                        "passed": outcome["passed"],
                        "handoff_ready": report.get("handoff_ready", False),
                    }
                ),
                flush=True,
            )
        return report

    desktop_check.wait_until = wait_until
    result = desktop_check.main(
        SimpleNamespace(
            human=True,
            visible=True,
            profiles=None,
            speech_cache=args.speech_cache.resolve(),
            runtime_root=args.runtime_root.resolve(),
            case="ja",
            theme="light",
            output=None,
            widths="1180",
        ),
        before_human=before_human,
    )
    return result if outcome.get("passed") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech-cache", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
