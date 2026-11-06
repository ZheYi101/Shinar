"""Device state signals must preserve normal gaps and report real IO failures."""

from types import SimpleNamespace
import pytest

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QAudioFormat, QtAudio

from lingualoop.desktop.pcm_audio import PcmAudioBridge
from lingualoop.realtime.pcm import DeviceFormat
from test_desktop_workflow import qt_app  # noqa: F401


class DeviceStub(QObject):
    stateChanged = Signal(QtAudio.State)

    def __init__(self, *args):
        super().__init__()
        self._error = QtAudio.Error.NoError
        self._state = QtAudio.State.ActiveState
        self.stops = self.resets = 0
        self.written = bytearray()

    def setBufferSize(self, size):
        pass

    def setVolume(self, volume):
        pass

    def error(self):
        return self._error

    def state(self):
        return self._state

    def stop(self):
        self.stops += 1

    def reset(self):
        self.resets += 1

    def start(self):
        return self

    def bytesFree(self):
        return 9600

    def processedUSecs(self):
        return 0

    def write(self, data):
        self.written.extend(data)
        return len(data)


def bridge_with_stub_devices(monkeypatch):
    import lingualoop.desktop.pcm_audio as module

    monkeypatch.setattr(module, "QAudioSource", DeviceStub)
    monkeypatch.setattr(module, "QAudioSink", DeviceStub)
    bridge = PcmAudioBridge(None)
    bridge.input_device = bridge.output_device = SimpleNamespace(isNull=lambda: False)
    fmt = QAudioFormat()
    fmt.setSampleRate(48000)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    bridge.input_format = bridge.output_format = fmt
    bridge.input_spec = bridge.output_spec = DeviceFormat(48000, 1, "int16")
    bridge.open()
    return bridge


def test_idle_underrun_keeps_the_output_generation_and_finishes_only_after_end(qt_app, monkeypatch):
    bridge = bridge_with_stub_devices(monkeypatch)
    faults, drained = [], []
    bridge.fault.connect(faults.append)
    bridge.drained.connect(drained.append)
    try:
        bridge.begin_output("one")
        bridge.enqueue("one", b"\0" * 960)
        bridge.sink._state = QtAudio.State.IdleState
        bridge.sink._error = QtAudio.Error.UnderrunError
        bridge.sink.stateChanged.emit(QtAudio.State.IdleState)
        assert not faults and not drained and bridge.generation == "one"
        bridge.enqueue("one", b"\0" * 960)
        bridge.finish_output("one")
        assert drained == ["one"] and not faults
        assert len(bridge.sink.written) == 1920
    finally:
        bridge.close()


def test_audio_state_signal_handles_input_and_output_io_errors(qt_app, monkeypatch):
    bridge = bridge_with_stub_devices(monkeypatch)
    faults = []
    bridge.fault.connect(faults.append)
    try:
        bridge.begin_output("one")
        bridge.sink._error = QtAudio.Error.IOError
        bridge.sink.stateChanged.emit(QtAudio.State.StoppedState)
        assert faults == ["audio_output_failed"] and not bridge.generation
        bridge.source._error = QtAudio.Error.IOError
        bridge.source.stateChanged.emit(QtAudio.State.StoppedState)
        assert faults == ["audio_output_failed", "microphone_failed"]
        assert bridge.source.stops == 1
    finally:
        bridge.close()


@pytest.mark.parametrize("removed", [False, True])
def test_inventory_change_only_pauses_for_selected_device_removal(qt_app, monkeypatch, removed):
    import lingualoop.desktop.pcm_audio as module

    bridge = bridge_with_stub_devices(monkeypatch)
    device = lambda name: SimpleNamespace(
        id=lambda: name, isNull=lambda: False, isFormatSupported=lambda fmt: True
    )
    bridge.input_device, bridge.output_device = device("mic"), device("speaker")
    monkeypatch.setattr(module.QMediaDevices, "audioInputs", lambda: [device("mic")])
    monkeypatch.setattr(
        module.QMediaDevices,
        "audioOutputs",
        lambda: [device("unrelated")] if removed else [device("speaker"), device("unrelated")],
    )
    faults = []
    bridge.fault.connect(faults.append)
    try:
        bridge.begin_output("one")
        bridge._device_change()
        assert faults == (["audio_devices_changed"] if removed else [])
        assert bridge.generation == ("" if removed else "one")
    finally:
        bridge.close()


def test_error_callbacks_during_stop_do_not_recurse(qt_app, monkeypatch):
    bridge = bridge_with_stub_devices(monkeypatch)
    faults = []
    bridge.fault.connect(faults.append)
    bridge.source.stop = bridge._source_state
    bridge.sink.reset = bridge._sink_state
    try:
        bridge.source._error = QtAudio.Error.IOError
        bridge.sink._error = QtAudio.Error.IOError
        bridge._source_state()
        bridge._sink_state()
        assert faults == ["microphone_failed", "audio_output_failed"]
    finally:
        bridge.close()
