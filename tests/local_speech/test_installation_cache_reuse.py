"""Disposable caches must not turn an intact installation back into a download."""

import hashlib
import io
import json
import shutil
from types import SimpleNamespace
import zipfile

import httpx
import pytest

from shinar.local_speech.catalog import Artifact, ModelPackage
from shinar.local_speech.downloads import ModelStore
import shinar.local_speech.installation as installation
from shinar.local_speech.storage import atomic_json


def artifact(path, content):
    return Artifact(path=path, url="https://models.example/" + path,
                    size=len(content), sha256=hashlib.sha256(content).hexdigest())


def package(identity, path, content, *, task="runtime", adapter="resource"):
    return ModelPackage(
        id=identity, revision="v1", name=identity, task=task, adapter=adapter,
        languages=["en"], scenarios=["conversation"], streaming="batch",
        license_note="fixture", sources=["https://models.example"], notes="fixture",
        files=[artifact(path, content)], required_files=[path],
    )


@pytest.fixture
def runtime_inputs(tmp_path, monkeypatch):
    payload = {
        "python.exe": b"fake isolated python", "shared.bin": b"shared runtime resource",
        "test.whl": b"locked wheel contents", "model.onnx": b"installed model weights",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("uv/uv.exe", b"isolated installer")
    payload["uv.whl"] = output.getvalue()
    model = package("test-model", "model.onnx", payload["model.onnx"], task="stt", adapter="sensevoice")
    resources = {
        name: package("speech-resource-" + name, path, payload[path]).model_dump(mode="json")
        for name, path in (("python", "python.exe"), ("shared", "shared.bin"))
    }
    wheel = artifact("test.whl", payload["test.whl"])
    data = {
        "runtimes": {"ort-cpu": {"device": "cpu", "wheels": [wheel.model_dump()],
                                 "resources": ["shared"]}},
        "resources": resources, "uv": artifact("uv.whl", payload["uv.whl"]).model_dump(),
    }
    monkeypatch.setattr(installation, "manifest", lambda: data)
    monkeypatch.setattr(installation, "_check_platform", lambda: None)
    spec = installation.runtime_spec("ort-cpu")
    sources = tmp_path / "fixtures"
    sources.mkdir()
    for name, content in payload.items():
        (sources / name).write_bytes(content)
    return SimpleNamespace(model=model, spec=spec, data=data, payload=payload, sources=sources)


def install_package(root, model, inputs):
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=inputs.payload[request.url.path.lstrip("/")])
    )) as client:
        return ModelStore(root).install(model, client=client)


def seed_resources(root, inputs):
    for name in ("python", "shared"):
        install_package(root, installation.resource_package(name), inputs)


def ready_runtime(root, inputs, folder="original"):
    candidate = root / "runtimes" / folder
    (candidate / "Scripts").mkdir(parents=True)
    (candidate / "Scripts/python.exe").touch()
    atomic_json(candidate / "ready.json", {"ok": True, "fingerprint": inputs.spec.fingerprint})
    atomic_json(root / "runtimes/ort-cpu.json", {
        "folder": folder, "fingerprint": inputs.spec.fingerprint,
    })


def fail_download(*args, **kwargs):
    pytest.fail("intact installed assets must not be downloaded again")


def seed_reusable_installer(root, inputs, monkeypatch):
    wheelhouse = root / "wheelhouses" / inputs.spec.fingerprint
    wheelhouse.mkdir(parents=True)
    (wheelhouse / "test.whl").write_bytes(inputs.payload["test.whl"])
    monkeypatch.setattr(ModelStore, "fetch_artifact",
                        lambda store, item, **kwargs: inputs.sources / item.path)
    executable = installation._uv(ModelStore(root), None, lambda *args: None)
    return wheelhouse, executable


def test_installed_model_and_ready_runtime_need_no_download_after_cleanup(
    tmp_path, runtime_inputs, monkeypatch
):
    root, inputs = tmp_path / "cache", runtime_inputs
    install_package(root, inputs.model, inputs)
    seed_resources(root, inputs)
    ready_runtime(root, inputs)
    shutil.rmtree(root / "downloads")
    monkeypatch.setattr(ModelStore, "fetch_artifact", fail_download)
    plan = installation.make_plan(root, inputs.model, "en", "cpu")
    assert plan.download_bytes == plan.disk_bytes == 0
    assert plan.package_id == inputs.model.id and plan.runtime_id == inputs.spec.id
    assert installation.runtime_plan(root, "ort-cpu").download_bytes == 0
    with httpx.Client(transport=httpx.MockTransport(fail_download)) as client:
        assert ModelStore(root).install(inputs.model, client=client).is_dir()
    assert installation.prepare_managed_runtime(root, "ort-cpu")["prepared"]
    assert not (root / "downloads").exists()


def test_unprepared_environment_reuses_installed_resources_and_verified_wheelhouse(
    tmp_path, runtime_inputs, monkeypatch
):
    root, inputs = tmp_path / "cache", runtime_inputs
    install_package(root, inputs.model, inputs)
    seed_resources(root, inputs)
    seed_reusable_installer(root, inputs, monkeypatch)
    shutil.rmtree(root / "downloads")
    monkeypatch.setattr(ModelStore, "fetch_artifact", fail_download)
    assert installation.make_plan(root, inputs.model, "en", "cpu").download_bytes == 0
    plan = installation.runtime_plan(root, "ort-cpu")
    assert plan.download_bytes == 0 and plan.disk_bytes > 0

    def install_environment(root, uv, python_home, folder, wheelhouse, spec, cancel):
        assert uv.read_bytes() == b"isolated installer"
        assert (python_home / "python.exe").read_bytes() == inputs.payload["python.exe"]
        assert (wheelhouse / "test.whl").read_bytes() == inputs.payload["test.whl"]
        python = folder / "Scripts/python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        return python

    monkeypatch.setattr(installation, "_install_environment", install_environment)
    monkeypatch.setattr(installation, "probe_managed_runtime", lambda *args, **kwargs: {"ok": True})
    assert installation.prepare_managed_runtime(root, "ort-cpu")["prepared"]
    assert not (root / "downloads").exists()


def test_repair_plan_and_execution_still_rebuild_a_ready_environment(
    tmp_path, runtime_inputs, monkeypatch
):
    root, inputs = tmp_path / "cache", runtime_inputs
    seed_resources(root, inputs)
    ready_runtime(root, inputs)
    shutil.rmtree(root / "downloads")
    assert installation.runtime_plan(root, "ort-cpu").disk_bytes == 0
    repair = installation.runtime_plan(root, "ort-cpu", repair=True)
    assert repair.download_bytes == len(inputs.payload["test.whl"]) + len(inputs.payload["uv.whl"])
    assert repair.disk_bytes > 0
    old_pointer = (root / "runtimes/ort-cpu.json").read_bytes()
    observed = []
    original_plan = installation.runtime_plan

    def plan(root, runtime_id, *, repair=False):
        observed.append(repair)
        return original_plan(root, runtime_id, repair=repair)

    monkeypatch.setattr(installation, "runtime_plan", plan)
    monkeypatch.setattr(installation, "_uv", lambda *args: (_ for _ in ()).throw(RuntimeError("stop")))
    with pytest.raises(RuntimeError, match="stop"):
        installation.prepare_managed_runtime(root, "ort-cpu", repair=True)
    assert observed == [True]
    assert (root / "runtimes/ort-cpu.json").read_bytes() == old_pointer
    assert installation.managed_status(root, "ort-cpu")["prepared"]


def test_stale_or_incomplete_model_is_not_counted_as_installed(tmp_path, runtime_inputs):
    root, inputs = tmp_path / "cache", runtime_inputs
    model_path = install_package(root, inputs.model, inputs)
    seed_resources(root, inputs)
    ready_runtime(root, inputs)
    shutil.rmtree(root / "downloads")
    (model_path / "model.onnx").unlink()
    assert installation.make_plan(root, inputs.model, "en", "cpu").download_bytes == inputs.model.download_bytes
    (model_path / "model.onnx").write_bytes(inputs.payload["model.onnx"])
    changed = inputs.model.model_copy(update={"revision": "v2"})
    assert installation.make_plan(root, changed, "en", "cpu").download_bytes == changed.download_bytes


def test_wrong_size_cached_blob_does_not_hide_missing_download(tmp_path, runtime_inputs):
    root, inputs = tmp_path / "cache", runtime_inputs
    seed_resources(root, inputs)
    ready_runtime(root, inputs)
    blob = root / "downloads" / inputs.model.files[0].sha256
    blob.write_bytes(b"partial")
    assert installation.make_plan(root, inputs.model, "en", "cpu").download_bytes == inputs.model.download_bytes


def test_wheelhouse_reuse_checks_sha_and_replaces_same_size_corruption(
    tmp_path, runtime_inputs, monkeypatch
):
    root, inputs = tmp_path / "cache", runtime_inputs
    wheelhouse, _ = seed_reusable_installer(root, inputs, monkeypatch)
    target = wheelhouse / "test.whl"
    target.write_bytes(b"x" * len(inputs.payload["test.whl"]))
    fetched = []

    def fetch(store, item, **kwargs):
        fetched.append(item.sha256)
        return inputs.sources / item.path

    monkeypatch.setattr(ModelStore, "fetch_artifact", fetch)
    installation._prepare_wheelhouse(ModelStore(root), inputs.spec, None, lambda *args: None, lambda stage: None)
    assert fetched == [inputs.spec.wheels[0]["sha256"]]
    assert target.read_bytes() == inputs.payload["test.whl"]
    fetched.clear()
    installation._prepare_wheelhouse(ModelStore(root), inputs.spec, None, lambda *args: None, lambda stage: None)
    assert fetched == []


def test_bootstrap_reuse_requires_executable_sha_bound_to_original_artifact(
    tmp_path, runtime_inputs, monkeypatch
):
    root, inputs = tmp_path / "cache", runtime_inputs
    _, executable = seed_reusable_installer(root, inputs, monkeypatch)
    receipt = json.loads((executable.parent / "ready.json").read_text())
    assert receipt["artifact_sha256"] == inputs.data["uv"]["sha256"]
    assert receipt["sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    monkeypatch.setattr(ModelStore, "fetch_artifact", fail_download)
    assert installation._uv(ModelStore(root), None, lambda *args: None) == executable
    executable.write_bytes(b"x" * receipt["size"])
    fetched = []

    def fetch(store, item, **kwargs):
        fetched.append(item.sha256)
        return inputs.sources / item.path

    monkeypatch.setattr(ModelStore, "fetch_artifact", fetch)
    installation._uv(ModelStore(root), None, lambda *args: None)
    assert fetched == [inputs.data["uv"]["sha256"]]
    assert executable.read_bytes() == b"isolated installer"
    receipt["artifact_sha256"] = "0" * 64
    atomic_json(executable.parent / "ready.json", receipt)
    fetched.clear()
    installation._uv(ModelStore(root), None, lambda *args: None)
    assert fetched == [inputs.data["uv"]["sha256"]]
