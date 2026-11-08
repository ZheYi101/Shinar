"""Synthetic RTC/device doubles for both regression and visible probes."""

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtMultimedia import QAudioFormat


class SyntheticBridge(QObject):
    capture = Signal(object, bytes)
    rendered = Signal(object, bytes)
    credit = Signal()
    drained = Signal(str)
    fault = Signal(str)
    started = Signal()

    def __init__(self):
        super().__init__()
        self.generation = ""
        self.frames = []
        self.opened = self.recording = False
        self.input_format = QAudioFormat()
        self.input_format.setSampleRate(48000)
        self.input_format.setChannelCount(1)
        self.input_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

    def formats(self):
        fmt = {"rate": 48000, "channels": 1, "sample": "int16"}
        return {"input_format": fmt, "output_format": fmt}

    def open(self):
        self.opened = True

    def resume(self):
        self.recording = True
        self.started.emit()

    def mute(self):
        self.recording = False

    def begin_output(self, generation):
        self.generation = generation

    def enqueue(self, generation, data):
        if generation == self.generation:
            self.frames.append((generation, data))
            self.credit.emit()

    def finish_output(self, generation):
        if generation == self.generation:
            QTimer.singleShot(0, lambda: self.drained.emit(generation))

    def stop_output(self):
        self.generation = ""

    def close(self):
        self.mute()
        self.stop_output()
        self.opened = False


class SyntheticRtc:
    def __init__(self, identity, on_event):
        self.id, self.emit = identity, on_event
        self.generation = ""
        self.closed = False
        self.calls = []
        self.paused_audio = None
        self.mic_generation = 0

    async def start(self, config):
        return {"synthetic_rtc": True}

    async def request(self, kind, payload=b"", **fields):
        self.calls.append(kind)
        if kind == "output_begin":
            self.generation = fields["generation"]
        elif kind == "segment":
            self.event("playback", b"\0" * 1920, generation=self.generation)
        elif kind == "output_done":
            self.event("output_drained", generation=self.generation)
        elif kind == "cancel_output":
            self.generation = ""
        elif kind == "resume":
            self.mic_generation += 1
            return {"mic_generation": self.mic_generation}
        elif kind == "pause":
            snapshot = self.paused_audio or ((fields, payload) if payload else None)
            if snapshot:
                header, data = snapshot
                self.event(
                    "input_paused",
                    data,
                    utterance=header["utterance"],
                    revision=header["revision"] + 1,
                    pause_id=fields["pause_id"],
                    mic_generation=self.mic_generation,
                )
            return {"has_input": bool(snapshot)}
        elif kind in {"discard_input", "mute"}:
            self.paused_audio = None
        return {"accepted": True}

    async def send(self, kind, payload=b"", **fields):
        self.calls.append(kind)

    def event(self, kind, payload=b"", **fields):
        self.emit({"kind": kind, "voice_session": self.id, **fields}, payload)

    async def close(self):
        self.closed = True


class Probe(QObject):
    finished = Signal(str)

    def __init__(self, error="", *, immediate=True):
        super().__init__()
        self.error, self.immediate = error, immediate
        self.started = self.closed = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.finished.emit(self.error))

    def start(self):
        self.started = True
        if self.immediate:
            self.timer.start(0)

    def close(self):
        self.closed = True
        self.timer.stop()


def configure_call(vm, monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.runtime as module

    monkeypatch.setattr(module, "managed_status", lambda *args: {"prepared": True})
    import shinar.desktop.voice.continuous.preparation as preparation
    import shinar.desktop.voice.continuous.work as work

    monkeypatch.setattr(preparation, "managed_status", lambda *args: {"prepared": True})
    monkeypatch.setattr(preparation, "prepared_assets", lambda *args: True)
    monkeypatch.setattr(work, "vad_path", lambda *args, **kwargs: tmp_path / "vad.onnx")
    monkeypatch.setattr(module, "vad_path", lambda *args, **kwargs: tmp_path / "vad.onnx")
    (tmp_path / "vad.onnx").touch()
    from shinar.realtime.local_server import ARCHIVE_NAME

    call = vm.voice.call
    (call.root / "sfu").mkdir(parents=True)
    (call.root / "sfu" / ARCHIVE_NAME).touch()
    call.bridge_factory = SyntheticBridge
    call.process_factory = SyntheticRtc
    return call
