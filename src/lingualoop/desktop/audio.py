"""Main-thread Qt audio capture/playback with session-scoped temporary files."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from lingualoop.core.voice import SpeechSegment

from PySide6.QtCore import QCoreApplication, QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import (
    QAudioInput,
    QAudioOutput,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaFormat,
    QMediaPlayer,
    QMediaRecorder,
)


class AudioController(QObject):
    recorded = Signal(bytes)
    errorOccurred = Signal(str)
    stateChanged = Signal(str)
    durationChanged = Signal(int)
    devicesChanged = Signal()
    queueChanged = Signal()
    segmentStarted = Signal(object)
    MAX_QUEUE_SEGMENTS = 3
    MAX_QUEUE_BYTES = 24 * 1024**2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._directory = None
        self._capture = QMediaCaptureSession(self)
        self._input = QAudioInput(self)
        self._recorder = QMediaRecorder(self)
        self._capture.setAudioInput(self._input)
        self._capture.setRecorder(self._recorder)
        media_format = QMediaFormat(QMediaFormat.FileFormat.Wave)
        media_format.setAudioCodec(QMediaFormat.AudioCodec.Wave)
        self._recorder.setMediaFormat(media_format)
        self._recorder.setAudioChannelCount(1)
        self._recorder.setAudioSampleRate(16000)
        self._recorder.recorderStateChanged.connect(self._recording_state)
        self._recorder.durationChanged.connect(self._duration)
        self._recorder.errorOccurred.connect(
            lambda *_: self._fail(
                QCoreApplication.translate("Desktop", "录音失败，请检查麦克风权限和音频设备。")
            )
        )
        self._player = QMediaPlayer(self)
        self._output = QAudioOutput(self)
        self.selected_input_id = bytes(self._input.device().id()).hex()
        self.selected_output_id = bytes(self._output.device().id()).hex()
        self._player.setAudioOutput(self._output)
        self._player.errorOccurred.connect(
            lambda *_: self._fail(
                QCoreApplication.translate(
                    "Desktop", "播放失败，文字回复已保留，可以重播或继续输入。"
                )
            )
        )
        self._player.playbackStateChanged.connect(self._playback_state)
        self._devices = QMediaDevices(self)
        self._devices.audioInputsChanged.connect(self.devicesChanged)
        self._devices.audioOutputsChanged.connect(self.devicesChanged)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self.stop_recording)
        self._pending_recording = False
        self._segments = []
        self._active_segment = None
        self._queue_generation = ""
        self._segment_serial = 0
        self._player.mediaStatusChanged.connect(self._media_status)

    @property
    def input_devices(self):
        return [
            {"id": bytes(device.id()).hex(), "name": device.description()}
            for device in QMediaDevices.audioInputs()
        ]

    @property
    def output_devices(self):
        return [
            {"id": bytes(device.id()).hex(), "name": device.description()}
            for device in QMediaDevices.audioOutputs()
        ]

    def select_device(self, device_id, *, output=False):
        devices = QMediaDevices.audioOutputs() if output else QMediaDevices.audioInputs()
        device = next((item for item in devices if bytes(item.id()).hex() == device_id), None)
        if device is not None:
            (self._output if output else self._input).setDevice(device)
            if output:
                self.selected_output_id = device_id
            else:
                self.selected_input_id = device_id
            self.devicesChanged.emit()

    def _dir(self):
        if self._directory is None:
            self._directory = TemporaryDirectory(prefix="lingualoop-audio-")
        return Path(self._directory.name)

    def start_recording(self):
        if self._pending_recording:
            return
        if not QMediaDevices.audioInputs():
            self._fail(
                QCoreApplication.translate(
                    "Desktop", "没有可用麦克风，请连接设备后重试，或使用文字输入。"
                )
            )
            return
        self._player.stop()
        self._pending_recording = True
        self._recorder.setOutputLocation(QUrl.fromLocalFile(str(self._dir() / "recording.wav")))
        self._recorder.record()
        if self._recorder.error() != QMediaRecorder.Error.NoError:
            self._pending_recording = False
            return
        self._timer.start()

    def stop_recording(self):
        self._timer.stop()
        self._recorder.stop()

    def cancel_recording(self):
        self._pending_recording = False
        self._timer.stop()
        self._recorder.stop()
        self._remove_recording()
        self.stateChanged.emit("idle")

    def _recording_state(self, state):
        if state == QMediaRecorder.RecorderState.RecordingState:
            self.stateChanged.emit("recording")
        elif state == QMediaRecorder.RecorderState.StoppedState and self._pending_recording:
            self._pending_recording = False
            try:
                audio = (self._dir() / "recording.wav").read_bytes()
            except OSError:
                self._fail(QCoreApplication.translate("Desktop", "未能读取录音，请重录。"))
            else:
                self._recorder.setOutputLocation(QUrl())
                self._remove_recording()
                self.recorded.emit(audio)

    def _remove_recording(self):
        if self._directory is not None:
            try:
                (Path(self._directory.name) / "recording.wav").unlink(missing_ok=True)
            except OSError:
                # Some audio backends release the file asynchronously. clear()
                # retries cleanup after capture and playback have stopped.
                pass

    def _duration(self, duration):
        self.durationChanged.emit(duration // 1000)
        if duration >= 60000:
            self.stop_recording()

    def play(self, audio):
        self.stop_playback()
        if not QMediaDevices.audioOutputs():
            self._fail(QCoreApplication.translate("Desktop", "没有可用播放设备，文字回复已保留。"))
            return
        self._player.stop()
        self._player.setSource(QUrl())
        path = self._dir() / "reply.wav"
        try:
            path.write_bytes(audio)
        except OSError:
            self._fail(
                QCoreApplication.translate("Desktop", "无法保存临时播放文件，请停止播放后重试。")
            )
            return
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def stop_playback(self):
        self._queue_generation = ""
        self._player.stop()
        self._player.setSource(QUrl())
        self._discard_segments()

    @property
    def queued_count(self) -> int:
        return len(self._segments) + int(self._active_segment is not None)

    @property
    def queued_bytes(self) -> int:
        items = self._segments + ([self._active_segment] if self._active_segment else [])
        return sum(len(item[0].audio) for item in items)

    def begin_playback(self, generation: str) -> None:
        self.stop_playback()
        self._queue_generation = generation

    def enqueue(self, segment: SpeechSegment, generation: str) -> bool:
        """Main-thread bounded admission. False means the caller must await capacity."""
        if generation != self._queue_generation:
            raise RuntimeError("stale_audio_generation")
        if len(segment.audio) > self.MAX_QUEUE_BYTES:
            raise ValueError("speech_audio_too_large")
        if (
            self.queued_count >= self.MAX_QUEUE_SEGMENTS
            or self.queued_bytes + len(segment.audio) > self.MAX_QUEUE_BYTES
        ):
            return False
        if not QMediaDevices.audioOutputs():
            raise RuntimeError("audio_output_missing")
        self._segment_serial += 1
        path = self._dir() / f"segment-{self._segment_serial}.wav"
        path.write_bytes(segment.audio)
        self._segments.append((segment, path))
        if self._active_segment is None:
            self._play_next()
        self.queueChanged.emit()
        return True

    def _play_next(self) -> None:
        if not self._segments:
            self.queueChanged.emit()
            return
        self._active_segment = self._segments.pop(0)
        segment, path = self._active_segment
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()

    def _media_status(self, status) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia or not self._active_segment:
            return
        _, path = self._active_segment
        self._active_segment = None
        self._player.setSource(QUrl())
        self._remove_segment(path)
        self._play_next()
        self.queueChanged.emit()

    @staticmethod
    def _remove_segment(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # clear() retries after multimedia has released its file handles.

    def _discard_segments(self) -> None:
        items = self._segments + ([self._active_segment] if self._active_segment else [])
        self._segments = []
        self._active_segment = None
        for _, path in items:
            self._remove_segment(path)
        self.queueChanged.emit()

    def _playback_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState and self._active_segment:
            self.segmentStarted.emit(self._active_segment[0])
        self.stateChanged.emit(
            "playing" if state == QMediaPlayer.PlaybackState.PlayingState else "idle"
        )

    def _fail(self, message):
        self._pending_recording = False
        self._timer.stop()
        self.stateChanged.emit("error")
        self.errorOccurred.emit(message)

    def clear(self):
        self._pending_recording = False
        self._timer.stop()
        self._recorder.stop()
        self.stop_playback()
        self._recorder.setOutputLocation(QUrl())
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
        self.stateChanged.emit("idle")
