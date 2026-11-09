"""Pinned corpora are found by legacy g2p_en without runtime downloads."""

import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import pytest

from shinar.local_speech.offline_nltk import ARCHIVES, DIRECTORIES, configure_offline_nltk


def prepared_data(tmp_path):
    root = tmp_path / "nltk_data"
    for name in DIRECTORIES:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in ARCHIVES:
        path = root / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(path.stem + "/sample", b"synthetic corpus")
    return root


def nltk_stub(monkeypatch):
    found, network = [], []
    data = SimpleNamespace(path=["personal-home-cache"], find=lambda name, **kwargs: found.append((name, kwargs)))
    module = SimpleNamespace(data=data, download=lambda *args: network.append(args))
    monkeypatch.setitem(sys.modules, "nltk", module)
    return module, found, network


def test_owned_data_replaces_home_search_paths_and_download_is_rejected(tmp_path, monkeypatch):
    root = prepared_data(tmp_path)
    nltk, found, network = nltk_stub(monkeypatch)
    configure_offline_nltk(root)
    assert nltk.data.path == [str(root)]
    assert found == [(name, {"paths": [str(root)]}) for name in ARCHIVES]
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        nltk.download("cmudict")
    assert network == []


@pytest.mark.parametrize("missing", [*ARCHIVES, *DIRECTORIES[1:]])
def test_missing_owned_data_fails_before_g2p_can_request_network(tmp_path, monkeypatch, missing):
    root = prepared_data(tmp_path)
    path = root / missing
    if path.is_file():
        path.unlink()
    else:
        path.rmdir()
    _, found, network = nltk_stub(monkeypatch)
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        configure_offline_nltk(root)
    assert found == [] and network == []


def test_lookup_failure_has_stable_error_and_cannot_download(tmp_path, monkeypatch):
    root = prepared_data(tmp_path)
    nltk, _, network = nltk_stub(monkeypatch)

    def missing(*args, **kwargs):
        raise LookupError("unusable archive")

    nltk.data.find = missing
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        configure_offline_nltk(root)
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        nltk.download("repair")
    assert network == []


def test_melo_install_retains_archives_and_expands_them(tmp_path, monkeypatch):
    from shinar.local_speech import installation

    nlp = tmp_path / "resources"
    for name in ARCHIVES:
        path = nlp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(path.stem + "/sample", b"synthetic corpus")
    monkeypatch.setattr(installation.ModelStore, "model_path", lambda *args: nlp)
    candidate = tmp_path / "runtime"
    installation._install_melo_support(tmp_path, candidate, None)
    for name in ARCHIVES:
        assert (candidate / "support/nltk_data" / name).read_bytes() == (nlp / name).read_bytes()
        assert (candidate / "support/nltk_data" / Path(name).with_suffix("") / "sample").read_bytes() == b"synthetic corpus"


def test_standalone_probe_and_worker_share_the_offline_guard(tmp_path, monkeypatch):
    root = Path(__file__).parents[2] / "src/shinar/local_speech"
    monkeypatch.syspath_prepend(str(root))
    guard = importlib.import_module("offline_nltk")
    seen = []

    def stop_before_frontend(path):
        seen.append(str(path))
        raise ValueError("speech_runtime_nltk_missing")

    monkeypatch.setattr(guard, "configure_offline_nltk", stop_before_frontend)
    probe = importlib.import_module("managed_runtime_probe")
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        probe.probe({"runtime_id": "melo-cpu", "gpu_index": 0, "resources": {"bert": "unused"}})
    worker = importlib.import_module("runtime_worker")
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        worker.load_model({"adapter": "melo_english", "nltk_path": str(tmp_path / "owned")}, 2)
    assert len(seen) == 2
    assert seen[1] == str(tmp_path / "owned")


def test_host_probe_returns_specific_missing_data_before_starting_process(tmp_path, monkeypatch):
    from shinar.local_speech import installation

    monkeypatch.setattr(installation, "run_bounded", lambda *args, **kwargs: pytest.fail("process started"))
    python = tmp_path / "candidate/Scripts/python.exe"
    with pytest.raises(ValueError, match="speech_runtime_nltk_missing"):
        installation.probe_managed_runtime(tmp_path, "melo-cpu", str(python))


def ready_melo(root, identity):
    from shinar.local_speech.installation import runtime_spec
    from shinar.local_speech.storage import atomic_json

    fingerprint = runtime_spec(identity).fingerprint
    folder = root / "runtimes" / (identity + "-candidate")
    (folder / "Scripts").mkdir(parents=True)
    (folder / "Scripts/python.exe").touch()
    atomic_json(folder / "ready.json", {"ok": True, "fingerprint": fingerprint})
    atomic_json(root / "runtimes" / (identity + ".json"), {"folder": folder.name, "fingerprint": fingerprint})
    return folder


def test_old_melo_layout_needs_repair_and_new_owned_data_restores_ready(tmp_path, monkeypatch):
    from shinar.local_speech import installation

    folder = ready_melo(tmp_path, "melo-cpu")
    monkeypatch.setattr(installation.ModelStore, "installed", lambda *args: True)
    old = installation.managed_status(tmp_path, "melo-cpu")
    assert not old["prepared"]
    assert old["repairRequired"] == "speech_runtime_nltk_missing"
    prepared_data(folder / "support")
    repaired = installation.managed_status(tmp_path, "melo-cpu")
    assert repaired["prepared"] and "repairRequired" not in repaired


def test_migration_keeps_known_repairable_melo_runtimes(tmp_path, monkeypatch):
    from shinar.local_speech import installation
    from shinar.local_speech.storage_migration import preview_migration

    source = tmp_path / "old"
    for identity in ("melo-cpu", "melo-cuda"):
        ready_melo(source, identity)
    monkeypatch.setattr(installation.ModelStore, "installed", lambda *args: True)
    plan = preview_migration(source, tmp_path / "new")
    assert plan.runtime_ids == ("melo-cpu", "melo-cuda")


def test_corrupt_marker_cannot_claim_repairable_melo_status(tmp_path, monkeypatch):
    from shinar.local_speech import installation
    from shinar.local_speech.storage import atomic_json
    from shinar.local_speech.storage_migration import preview_migration

    source = tmp_path / "old"
    folder = ready_melo(source, "melo-cpu")
    monkeypatch.setattr(installation.ModelStore, "installed", lambda *args: True)
    atomic_json(folder / "ready.json", {
        "ok": True, "fingerprint": "invalid", "repairRequired": "speech_runtime_nltk_missing",
    })
    status = installation.managed_status(source, "melo-cpu")
    assert not status["prepared"] and "repairRequired" not in status
    assert preview_migration(source, tmp_path / "new").runtime_ids == ()
