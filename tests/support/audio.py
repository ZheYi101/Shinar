"""Synthetic speech and Qt audio doubles; no physical devices or network calls."""

import asyncio
import io
import wave
from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtGui import QGuiApplication
from shinar.providers import MockLearningLLMProvider


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
            yield reply[position : position + 8]
            await asyncio.sleep(0.02)
