"""The Qt adapter freezes only its public runtime and local-speech directories."""

from types import SimpleNamespace

import pytest

from shinar.desktop.voice.continuous.runtime import CallRuntime


@pytest.mark.parametrize("local_enabled", [True, False])
def test_real_audio_process_receives_frozen_resource_roots(tmp_path, monkeypatch, local_enabled):
    import shinar.desktop.voice.continuous.runtime as module

    speech_root = tmp_path / "speech-library"
    local = SimpleNamespace(store=SimpleNamespace(root=speech_root),
                            enabled=lambda task: local_enabled)
    vm = SimpleNamespace(workbench=SimpleNamespace(storage_path=tmp_path / "data/library.sqlite3"),
                         local_speech=local)
    voice = SimpleNamespace(vm=vm, worker=None)
    runtime = CallRuntime(SimpleNamespace(), voice)
    monkeypatch.setattr(module, "managed_status", lambda *args: {"prepared": False})
    process = runtime.create_process("call")
    expected = (runtime.root, speech_root) if local_enabled else (runtime.root,)
    assert process.storage_roots == expected


def test_injected_audio_process_does_not_need_a_storage_extension(tmp_path):
    class Process:
        def __init__(self, identity, callback):
            self.identity = identity

    vm = SimpleNamespace(workbench=SimpleNamespace(storage_path=tmp_path / "data.sqlite3"))
    runtime = CallRuntime(SimpleNamespace(), SimpleNamespace(vm=vm, worker=None))
    runtime.process_factory = Process
    assert runtime.create_process("injected").identity == "injected"
