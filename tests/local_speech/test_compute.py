import asyncio
import json
import sys

import pytest

from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.compute import (
    ComputeSettings,
    load_compute,
    resolve_device,
    save_compute,
)
from shinar.local_speech.resources import resource_snapshot
from shinar.local_speech.runtime import child_environment, probe_runtime
from shinar.local_speech.service import LocalSpeechService
from shinar.local_speech.storage import atomic_json


def fp32():
    return next(p for p in load_catalog() if p.id == "sensevoice-fp32-20240717")


def hardware(free=6000):
    return {"gpus": [{"name": "Test GPU", "available_mb": free}]}


def test_gpu_first_for_measured_speedup_and_cpu_for_light_models():
    assert resolve_device(fp32(), ComputeSettings(), hardware())[0] == "cuda"
    package = next(p for p in load_catalog() if p.id == "sensevoice-int8-20240717")
    assert resolve_device(package, ComputeSettings(), hardware())[0] == "cpu"
    assert resolve_device(fp32(), ComputeSettings(stt_device="cpu"), hardware())[0] == "cpu"


@pytest.mark.parametrize(
    "settings,hw",
    [
        (ComputeSettings(), {"gpus": []}),
        (ComputeSettings(), hardware(2000)),
        (ComputeSettings(vram_budget_mb=1024), hardware()),
        (ComputeSettings(gpu_index=1), hardware()),
    ],
)
def test_auto_reports_resource_fallback_and_forced_gpu_never_silently_falls_back(settings, hw):
    device, reason = resolve_device(fp32(), settings, hw)
    assert device == "cpu" and "自动改用 CPU" in reason
    with pytest.raises(ValueError, match="未自动改用 CPU"):
        resolve_device(fp32(), settings.model_copy(update={"stt_device": "cuda"}), hw)


def test_joint_memory_budget_is_not_per_model_budget():
    assert resolve_device(fp32(), ComputeSettings(), hardware(), occupied_mb=2000)[0] == "cpu"


def test_settings_persist_without_touching_learning_data(tmp_path):
    settings = ComputeSettings(local_stt=True, stt_device="cuda", idle_seconds=30)
    save_compute(tmp_path, settings)
    assert load_compute(tmp_path) == settings
    assert {path.name for path in tmp_path.iterdir()} == {"compute.json", ".storage.lock"}


def test_unsupported_process_telemetry_is_unknown_not_zero(monkeypatch):
    import shinar.local_speech.resources as module

    monkeypatch.setattr(
        module,
        "_query",
        lambda args: ["0, Test, 8192, 3000, 67"] if "--query-gpu=" in args[0] else ["777, [N/A]"],
    )
    result = resource_snapshot([777])
    assert result["gpus"][0]["utilization"] == 67
    assert result["speech_process_mb"] is None
    assert resource_snapshot([])["speech_process_mb"] == 0


def test_child_environment_has_no_cloud_credentials_or_python_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("SOME_TOKEN", "private")
    monkeypatch.setenv("PYTHONPATH", "unsafe")
    env = child_environment()
    assert not {"OPENAI_API_KEY", "SOME_TOKEN", "PYTHONPATH"} & env.keys()
    assert env["HF_HUB_OFFLINE"] == "1"


def test_runtime_probe_rejects_cpu_fallback(monkeypatch):
    import shinar.local_speech.runtime as module

    monkeypatch.setattr(module, "run_bounded", lambda *_, **__: '{"ok": true, "device": "cpu"}')
    with pytest.raises(RuntimeError, match="GPU"):
        probe_runtime(sys.executable, "cuda")


def test_reports_do_not_cross_device_or_gpu_index(tmp_path):
    from shinar.local_speech.downloads import ModelStore
    from shinar.local_speech.library import matching_reports
    package = fp32()
    hw = {**hardware(), "platform": "Windows", "architecture": "AMD64", "cpu": "CPU", "logical_cpus": 8}
    report = {"schema": 1, "language": "ja", "hardware": hw,
              "model_fingerprints": {package.id: package.fingerprint},
              "metrics": {"runtime_versions": {package.id: "1.23.2"},
                          "devices": {package.id: "cuda"}, "gpu_index": 0, "threads_per_model": 2}}
    atomic_json(tmp_path / "reports/gpu.json", report)
    store = ModelStore(tmp_path)
    assert matching_reports(store, package, "ja", hw, "cuda", 0)
    assert not matching_reports(store, package, "ja", hw, "cpu")
    assert not matching_reports(store, package, "ja", hw, "cuda", 1)


@pytest.mark.parametrize("idle", [0, 120])
def test_local_worker_reused_then_closed_and_keeps_audio_out_of_files(tmp_path, monkeypatch, idle):
    import shinar.local_speech.service as module

    monkeypatch.setattr(module, "detect_hardware", lambda _: hardware())
    monkeypatch.setattr(module, "runtime_python", lambda *_: sys.executable)
    monkeypatch.setattr(module, "runtime_status", lambda *_: {"prepared": True})
    monkeypatch.setattr(
        module,
        "matching_reports",
        lambda *args: [
            {"metrics": {"sequential": {"stt": [{"nonempty": True, "compute_ms": 42}]}}}
        ],
    )
    save_compute(tmp_path, ComputeSettings(idle_seconds=idle))
    service = LocalSpeechService(tmp_path)
    package = next(p for p in load_catalog() if p.id == "sensevoice-int8-20240717")
    monkeypatch.setattr(service.store, "installed", lambda _: True)
    atomic_json(
        tmp_path / "selections.json",
        {"zh:conversation:stt": {"id": package.id, "fingerprint": package.fingerprint}},
    )
    created = []

    class Process:
        pid, returncode = 123456, None

        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdin = self

        def write(self, data):
            request = json.loads(data)
            assert request["model"]["provider"] == "cpu"
            self.stdout.feed_data(
                json.dumps(
                    {
                        "ok": True,
                        "result": {"text": "测试", "compute_ms": 42, "load_ms": 7, "cold": False},
                    }
                ).encode()
                + b"\n"
            )

        async def drain(self):
            pass

        def close(self):
            self.writer_closed = True

        async def wait_closed(self):
            pass

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def spawn(*args, **kwargs):
        assert "inference_worker.py" in str(args[1])
        process = Process()
        created.append(process)
        return process

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(
        module,
        "terminate_tree",
        lambda pid: next(p for p in reversed(created) if p.returncode is None).kill(),
    )

    async def run():
        assert await service.transcribe(b"private audio", "zh") == "测试"
        assert await service.transcribe(b"private audio", "zh") == "测试"
        assert len(created) == (1 if idle else 2)
        assert bool(service.pids) == bool(idle)
        await service.close()
        assert not service.pids and created[0].returncode == -9

    asyncio.run(run())
    assert {p.name for p in tmp_path.iterdir()} == {
        "selections.json", "compute.json", ".locks", ".storage.lock",
    }
