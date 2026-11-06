import hashlib
import json
from pathlib import Path
from threading import Event

import pytest

from lingualoop.local_speech.catalog import Artifact, load_catalog
from lingualoop.local_speech.compute import ComputeSettings, resolve_device
from lingualoop.local_speech.downloads import DownloadCancelled, ModelStore
from lingualoop.local_speech.installation import (
    manifest,
    managed_status,
    prepare_managed_runtime,
    runtime_spec,
)
from lingualoop.local_speech.model_profile import (
    accepted_terms,
    measurement_identity,
    voice_choice,
    voices,
)
from lingualoop.local_speech.storage import atomic_json


def test_locked_runtime_artifacts_and_bundled_frontend_have_verified_identity():
    data = manifest()
    assert set(data["runtimes"]) == {
        "ort-cpu",
        "ort-cuda",
        "voicevox-cpu",
        "melo-cpu",
        "melo-cuda",
        "rtc-cpu",
    }
    root = Path(__file__).parents[2] / "src/lingualoop/local_speech/runtime_resources"
    for runtime in data["runtimes"].values():
        for item in runtime["wheels"]:
            if "resource" in item:
                content = (root / item["resource"]).read_bytes()
                assert len(content) == item["size"]
                assert hashlib.sha256(content).hexdigest() == item["sha256"]
            else:
                assert Artifact.model_validate(item).url.startswith("https://")
    for name, expected in data["support_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    for name in ("melo-cpu", "melo-cuda"):
        wheels = data["runtimes"][name]["wheels"]
        assert next(w for w in wheels if w["path"].startswith("soundfile-"))["path"].endswith(
            "win_amd64.whl"
        )
        assert any(w["path"].startswith("torchaudio-2.9.1") for w in wheels)


def test_native_voice_and_device_choices_do_not_change_existing_defaults(tmp_path):
    vv = next(p for p in load_catalog() if p.id == "voicevox-japanese")
    melo = next(p for p in load_catalog() if p.id == "melo-english-en")
    assert voice_choice(tmp_path, vv.id)["style_id"] == 3
    assert len(voices(melo.id)) == 5
    assert not accepted_terms(tmp_path, vv)
    atomic_json(tmp_path / "voice-terms.json", {vv.id: vv.fingerprint})
    assert accepted_terms(tmp_path, vv)
    changed = vv.model_copy(update={"revision": "new-version"})
    assert not accepted_terms(tmp_path, changed)
    with pytest.raises(ValueError):
        resolve_device(vv, ComputeSettings(tts_device="cuda"), {"gpus": []})
    assert resolve_device(melo, ComputeSettings(), {"gpus": [{"available_mb": 8192}]})[0] == "cuda"
    before = measurement_identity(tmp_path, melo, "cuda")
    atomic_json(tmp_path / "voices.json", {melo.id: voices(melo.id)[1]["id"]})
    assert measurement_identity(tmp_path, melo, "cuda") != before
    assert measurement_identity(tmp_path, melo, "cuda", before["voice_id"]) == before
    assert not (tmp_path / "selections.json").exists()


def test_failed_repair_preserves_the_previous_ready_environment(tmp_path, monkeypatch):
    import lingualoop.local_speech.installation as module

    spec = runtime_spec("voicevox-cpu")
    old = tmp_path / "runtimes/old"
    (old / "Scripts").mkdir(parents=True)
    (old / "Scripts/python.exe").touch()
    atomic_json(old / "ready.json", {"ok": True, "fingerprint": spec.fingerprint})
    pointer = tmp_path / "runtimes/voicevox-cpu.json"
    atomic_json(pointer, {"folder": "old", "fingerprint": spec.fingerprint})
    original = pointer.read_bytes()
    monkeypatch.setattr(ModelStore, "installed", lambda *args: True)
    monkeypatch.setattr(module, "_check_platform", lambda: None)
    monkeypatch.setattr(module, "_uv", lambda *args: tmp_path / "uv.exe")
    monkeypatch.setattr(ModelStore, "install", lambda *args, **kwargs: tmp_path)
    blob = tmp_path / "blob"
    blob.write_bytes(b"wheel")
    monkeypatch.setattr(ModelStore, "fetch_artifact", lambda *args, **kwargs: blob)

    def fail(command, **kwargs):
        if "venv" in command:
            candidate = Path(command[-1])
            (candidate / "Scripts").mkdir(parents=True)
            raise RuntimeError("simulated environment failure")

    monkeypatch.setattr(module, "run_bounded", fail)
    with pytest.raises(RuntimeError):
        prepare_managed_runtime(tmp_path, spec.id, repair=True)
    assert pointer.read_bytes() == original
    assert managed_status(tmp_path, spec.id)["prepared"]
    assert [p.name for p in (tmp_path / "runtimes").iterdir() if p.is_dir()] == ["old"]


def test_cancelled_preparation_never_promotes_a_candidate(tmp_path, monkeypatch):
    import lingualoop.local_speech.installation as module

    monkeypatch.setattr(module, "_check_platform", lambda: None)
    monkeypatch.setattr(module, "_uv", lambda *args: tmp_path / "uv.exe")
    monkeypatch.setattr(ModelStore, "install", lambda *args, **kwargs: tmp_path)
    cancel = Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        prepare_managed_runtime(tmp_path, "voicevox-cpu", cancel=cancel)
    assert not (tmp_path / "runtimes/voicevox-cpu.json").exists()


def test_runtime_repair_cannot_replace_models_held_by_inference(tmp_path, monkeypatch):
    import lingualoop.local_speech.installation as module
    from lingualoop.local_speech.downloads import package_lock

    monkeypatch.setattr(module, "_check_platform", lambda: None)
    model = next(p for p in load_catalog() if p.id == "voicevox-japanese")
    with package_lock(tmp_path, model):
        with pytest.raises(RuntimeError, match="正在"):
            prepare_managed_runtime(tmp_path, "voicevox-cpu", repair=True)
    assert not (tmp_path / "runtimes/voicevox-cpu.json").exists()


def test_runtime_disk_failure_is_reported_before_downloading(tmp_path, monkeypatch):
    import lingualoop.local_speech.installation as module
    from types import SimpleNamespace

    monkeypatch.setattr(module, "_check_platform", lambda: None)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda root: SimpleNamespace(free=0))
    monkeypatch.setattr(module, "_uv", lambda *args: pytest.fail("must not download"))
    with pytest.raises(module.SpeechSetupError, match="speech_setup_disk_insufficient"):
        prepare_managed_runtime(tmp_path, "melo-cpu")


def test_preview_voice_does_not_replace_selected_live_voice(tmp_path, monkeypatch):
    import asyncio
    import lingualoop.local_speech.service as service_module
    import lingualoop.local_speech.installation as setup_module
    import lingualoop.local_speech.model_profile as profile_module
    from lingualoop.local_speech.service import LocalSpeechService
    from lingualoop.local_speech.profiles import instance_key

    package = next(p for p in load_catalog() if p.id == "voicevox-japanese")
    service = LocalSpeechService(tmp_path)
    monkeypatch.setattr(ModelStore, "installed", lambda *args: True)
    monkeypatch.setattr(service_module, "detect_hardware", lambda root: {"gpus": []})
    ready = lambda *args: {"prepared": True, "python": str(tmp_path / "python.exe")}
    monkeypatch.setattr(setup_module, "managed_status", ready)
    monkeypatch.setattr(profile_module, "managed_status", ready)
    observed = []

    def report(*args, **kwargs):
        observed.append(kwargs["voice_id"])
        return [{"metrics": {}}]

    monkeypatch.setattr(service_module, "matching_reports", report)
    atomic_json(tmp_path / "voice-terms.json", {package.id: package.fingerprint})
    atomic_json(
        tmp_path / "selections.json",
        {
            "ja:conversation:tts": {
                "id": package.id,
                "fingerprint": package.fingerprint,
                "voice_id": "zundamon-3",
            }
        },
    )
    atomic_json(tmp_path / "voices.json", {package.id: "zundamon-1"})
    ort = service.store.model_path(setup_module.resource_package("voicevox-ort")) / "lib"
    ort.mkdir(parents=True)
    (ort / "voicevox_onnxruntime.dll").touch()
    profile = asyncio.run(service.resolve("tts", "ja"))
    assert observed == ["zundamon-3"] and profile.spec["style_id"] == 3
    preview = profile_module.build_profile(service.store, package, "ja", "cpu")
    assert preview.spec["style_id"] == 1
    assert profile.spec["style_id"] == 3
    assert instance_key(profile.spec) == instance_key(preview.spec)
