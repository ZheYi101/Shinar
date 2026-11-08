"""Main-thread continuous device IO; DSP and inference live outside Qt."""

from collections import deque
from dataclasses import asdict
from time import monotonic

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QAudioSink, QMediaDevices, QtAudio

from shinar.realtime.pcm import DeviceFormat


class PcmAudioBridge(QObject):
    capture = Signal(object, bytes)
    rendered = Signal(object, bytes)
    credit = Signal()
    drained = Signal(str)
    fault = Signal(str)
    started = Signal()

    def __init__(self, audio_controller, parent=None):
        super().__init__(parent)
        self.audio = audio_controller
        self.source = self.sink = self.input_io = self.output_io = None
        self.generation = ""
        self._queue = deque()
        self._queued = 0
        self._finished = False
        self._stopping_input = self._stopping_output = False
        self._written = 0
        self.first_write_at = None
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._pump)
        self._devices = QMediaDevices(self)
        self._devices.audioInputsChanged.connect(self._device_change)
        self._devices.audioOutputsChanged.connect(self._device_change)

    @staticmethod
    def _format(device):
        if device.isNull():
            raise ValueError("audio_device_missing")
        preferred = QAudioFormat()
        preferred.setSampleRate(48000)
        preferred.setChannelCount(1)
        preferred.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        fmt = preferred if device.isFormatSupported(preferred) else device.preferredFormat()
        names = {
            QAudioFormat.SampleFormat.Int16: "int16",
            QAudioFormat.SampleFormat.Int32: "int32",
            QAudioFormat.SampleFormat.Float: "float32",
            QAudioFormat.SampleFormat.UInt8: "uint8",
        }
        if fmt.sampleFormat() not in names:
            raise ValueError("unsupported_audio_format")
        spec = DeviceFormat(fmt.sampleRate(), fmt.channelCount(), names[fmt.sampleFormat()])
        return fmt, spec

    def formats(self):
        # Reuse the selected devices, never silently substitute the default loudspeaker.
        inputs, outputs = QMediaDevices.audioInputs(), QMediaDevices.audioOutputs()
        self.input_device = next(
            (d for d in inputs if bytes(d.id()).hex() == self.audio.selected_input_id), None
        )
        self.output_device = next(
            (d for d in outputs if bytes(d.id()).hex() == self.audio.selected_output_id), None
        )
        if self.input_device is None or (
            self.audio.selected_output_id and self.output_device is None
        ):
            raise ValueError("audio_device_missing")
        if self.output_device is None:
            from PySide6.QtMultimedia import QAudioDevice

            self.output_device = QAudioDevice()
        self.input_format, self.input_spec = self._format(self.input_device)
        if self.output_device.isNull():
            # STT-only remains usable without an output device.
            self.output_format, self.output_spec = self.input_format, self.input_spec
        else:
            self.output_format, self.output_spec = self._format(self.output_device)
        return {"input_format": asdict(self.input_spec), "output_format": asdict(self.output_spec)}

    def open(self):
        self.close()
        self.source = QAudioSource(self.input_device, self.input_format, self)
        self.source.setBufferSize(self.input_format.bytesForDuration(80000))
        self.source.stateChanged.connect(self._source_state)
        if not self.output_device.isNull():
            self.sink = QAudioSink(self.output_device, self.output_format, self)
            self.sink.setBufferSize(self.output_format.bytesForDuration(60000))
            self.sink.setVolume(1.0)
            self.sink.stateChanged.connect(self._sink_state)
        self._timer.start()

    def resume(self):
        if not self.source:
            raise RuntimeError("audio_device_closed")
        self.input_io = self.source.start()
        if self.input_io is None or self.source.error() != QtAudio.Error.NoError:
            raise RuntimeError("microphone_open_failed")
        self.input_io.readyRead.connect(self._capture)
        self.started.emit()

    def mute(self):
        self.input_io = None
        if self.source:
            self._stopping_input = True
            try:
                self.source.stop()
            finally:
                self._stopping_input = False

    def flush_capture(self) -> None:
        """Forward the bounded bytes already in Qt before a voluntary pause."""
        self._capture()

    def _capture(self):
        if self.input_io is None:
            return
        available = self.input_io.bytesAvailable()
        if available > self.input_format.bytesForDuration(200000):
            self.mute()
            self.fault.emit("input_gap")
            return
        data = bytes(self.input_io.readAll())
        if data:
            delay = self.input_format.durationForBytes(len(data)) / 1000
            self.capture.emit({"captured_at": monotonic(), "capture_delay_ms": delay}, data)

    def begin_output(self, generation: str):
        self.stop_output()
        if not self.sink:
            raise RuntimeError("audio_output_missing")
        self.generation = generation
        self._written = 0
        self.first_write_at = None
        self.output_io = self.sink.start()
        if self.output_io is None or self.sink.error() != QtAudio.Error.NoError:
            self.stop_output()
            raise RuntimeError("audio_output_open_failed")

    def enqueue(self, generation: str, payload: bytes):
        if generation != self.generation:
            return
        if self._queued + len(payload) > self.output_format.bytesForDuration(3000000):
            self.stop_output()
            self.fault.emit("output_overflow")
            return
        self._queue.append(bytearray(payload))
        self._queued += len(payload)
        self._pump()

    def finish_output(self, generation: str):
        if generation == self.generation:
            self._finished = True
            self._pump()

    def _pump(self):
        if not self.output_io or not self.generation:
            return
        while self._queue:
            free = self.sink.bytesFree()
            free -= free % self.output_spec.frame_bytes
            if free <= 0:
                break
            pending = self._queue[0]
            written = self.output_io.write(bytes(pending[:free]))
            if written < 0:
                self.stop_output()
                self.fault.emit("audio_output_failed")
                return
            if not written:
                break
            played = bytes(pending[:written])
            del pending[:written]
            self._written += written
            self._queued -= written
            if self.first_write_at is None:
                self.first_write_at = monotonic()
            delay_us = max(
                0, self.output_format.durationForBytes(self._written) - self.sink.processedUSecs()
            )
            self.rendered.emit({"generation": self.generation, "delay_ms": delay_us / 1000}, played)
            if not pending:
                self._queue.popleft()
                self.credit.emit()
        if (
            self._finished
            and not self._queue
            and (
                self.sink.state() == QtAudio.State.IdleState
                or self.sink.processedUSecs() >= self.output_format.durationForBytes(self._written)
            )
        ):
            self._finished = False
            self.drained.emit(self.generation)

    def stop_output(self):
        self.generation = ""
        self._queue.clear()
        self._queued = 0
        self._finished = False
        self.output_io = None
        if self.sink:
            self._stopping_output = True
            try:
                self.sink.reset()
            finally:
                self._stopping_output = False

    @Slot()
    def _source_state(self) -> None:
        # PySide 6.11 exposes this signal as QAudio::State but its enum lives in
        # QtAudio. A zero-argument slot avoids the broken enum conversion.
        if (
            self.source
            and not self._stopping_input
            and self.source.error() != QtAudio.Error.NoError
        ):
            self.mute()
            self.fault.emit("microphone_failed")

    @Slot()
    def _sink_state(self) -> None:
        if not self.sink or self._stopping_output:
            return
        if self.sink.error() not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self.stop_output()
            self.fault.emit("audio_output_failed")
        # Idle/underrun is expected between sentences and at the end. The
        # timer observes drain; pumping here could reenter QIODevice.write().

    def _device_change(self):
        if self.source and not self.devices_available():
            self.mute()
            self.stop_output()
            self.fault.emit("audio_devices_changed")

    def devices_available(self) -> bool:
        """Ignore unrelated/default-device changes; never substitute another device."""
        for selected, fmt, devices in (
            (self.input_device, self.input_format, QMediaDevices.audioInputs()),
            (self.output_device, self.output_format, QMediaDevices.audioOutputs()),
        ):
            if selected.isNull():
                continue
            current = next((device for device in devices if device.id() == selected.id()), None)
            if current is None or not current.isFormatSupported(fmt):
                return False
        return True

    def close(self):
        self._timer.stop()
        self.mute()
        self.stop_output()
        for value in (self.source, self.sink):
            if value:
                value.deleteLater()
        self.source = self.sink = None
