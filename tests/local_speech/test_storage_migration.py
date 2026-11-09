"""Relocation is transactional and rebuilds runtimes at their final paths."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from shinar.configuration import speech_directory
from shinar.configuration_location import (
    SpeechStorageLocationError, load_speech_location, save_speech_location,
)
from shinar.local_speech.downloads import DownloadCancelled
from shinar.local_speech.storage import atomic_json
from shinar.local_speech.storage_lease import storage_lease, StorageMovedError
from shinar.local_speech.storage_migration import migrate_storage, preview_migration


def source_library(tmp_path):
    root = tmp_path / "source"
    model = root / "models/model/v1"
    model.mkdir(parents=True)
    content = b"a verified model"
    (model / "model.onnx").write_bytes(content)
    atomic_json(model / ".installed.json", {
        "fingerprint": "sample", "files": {"model.onnx": {
            "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        }},
    })
    atomic_json(root / "compute.json", {"local_stt": True})
    (root / "downloads").mkdir()
    (root / "downloads/resume.part").write_bytes(b"unfinished")
    (root / "learning.sqlite3").write_bytes(b"not part of speech resources")
    return root


def no_runtimes(monkeypatch):
    import shinar.local_speech.storage_migration as module

    monkeypatch.setattr(module, "manifest", lambda: {"runtimes": {}})
    return module


def test_saved_location_environment_precedence_and_temporary_data_isolation(tmp_path, monkeypatch):
    import shinar.configuration_location as module

    config, saved = tmp_path / "location.json", tmp_path / "saved"
    saved.mkdir()
    save_speech_location(saved, config)
    monkeypatch.setattr(module, "location_file", lambda value=None: config)
    for key in ("SHINAR_SPEECH_DIR", "LINGUALOOP_SPEECH_DIR", "SHINAR_DATA_DIR", "LINGUALOOP_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    assert speech_directory() == saved
    monkeypatch.setenv("SHINAR_DATA_DIR", str(tmp_path / "sandbox"))
    assert speech_directory() == tmp_path / "sandbox/speech"
    monkeypatch.setenv("SHINAR_SPEECH_DIR", str(tmp_path / "override"))
    assert speech_directory() == tmp_path / "override"


def test_unavailable_or_corrupt_saved_location_never_silently_falls_back(tmp_path):
    config, selected = tmp_path / "location.json", tmp_path / "external"
    selected.mkdir()
    save_speech_location(selected, config)
    selected.rmdir()
    with pytest.raises(SpeechStorageLocationError, match="unavailable"):
        load_speech_location(config)
    config.write_text("not json", encoding="utf-8")
    with pytest.raises(SpeechStorageLocationError, match="invalid"):
        load_speech_location(config)
    assert load_speech_location(tmp_path / "missing.json") is None


def test_preview_is_immutable_read_only_and_rejects_unsafe_destination(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    no_runtimes(monkeypatch)
    plan = preview_migration(source, target)
    assert not target.exists()
    assert plan.to_dict()["runtimeIds"] == []
    assert plan.copy_bytes > 0
    with pytest.raises(AttributeError):
        plan.copy_bytes = 0
    for invalid in (source, source / "nested", source.parent, Path(source.anchor)):
        with pytest.raises(ValueError, match="invalid_destination"):
            preview_migration(source, invalid)
    target.mkdir()
    (target / "personal.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="not_empty"):
        preview_migration(source, target)
    assert (target / "personal.txt").read_text() == "preserve"


def test_success_preserves_source_partials_links_and_retires_old_writes(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    config = tmp_path / "location.json"
    no_runtimes(monkeypatch)
    os.link(source / "models/model/v1/model.onnx", source / "downloads/hard-link")
    result = migrate_storage(source, target, config)
    assert result["sourceRetained"] and result["restartRequired"]
    assert load_speech_location(config) == target
    assert (source / "models/model/v1/model.onnx").is_file()
    assert (target / "models/model/v1/model.onnx").samefile(target / "downloads/hard-link")
    assert (target / "downloads/resume.part").read_bytes() == b"unfinished"
    assert not (target / "learning.sqlite3").exists()
    with pytest.raises(StorageMovedError):
        with storage_lease(source):
            pytest.fail("retired library accepted a writer")
    with storage_lease(source, exclusive=True):
        assert (source / "learning.sqlite3").read_bytes() == b"not part of speech resources"


def test_runtime_is_rebuilt_at_final_root_not_copied_from_source(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    module = no_runtimes(monkeypatch)
    (source / "runtimes/old").mkdir(parents=True)
    (source / "runtimes/old/absolute-path.txt").write_text(str(source), encoding="utf-8")
    monkeypatch.setattr(module, "manifest", lambda: {"runtimes": {"ort-cpu": {}}})
    monkeypatch.setattr(module, "managed_status", lambda root, name: {"prepared": root == source})
    monkeypatch.setattr(module, "runtime_plan", lambda *args, **kwargs: type("Plan", (), {"disk_bytes": 1024})())
    called = []

    def prepare(root, name, **kwargs):
        called.append((root, name))
        with storage_lease(root):
            (root / "runtime-created").write_text(str(root), encoding="utf-8")
        return {"prepared": True}

    monkeypatch.setattr(module, "prepare_managed_runtime", prepare)
    migrate_storage(source, target, tmp_path / "location.json")
    assert called == [(target, "ort-cpu")]
    assert (target / "runtime-created").read_text() == str(target)
    assert not (target / "runtimes/old").exists()


@pytest.mark.parametrize("failure", ["cancel", "corrupt", "runtime", "save"])
def test_failure_or_cancel_keeps_source_and_location_and_rolls_back_target(tmp_path, monkeypatch, failure):
    source, target = source_library(tmp_path), tmp_path / "target"
    config, cancel = tmp_path / "location.json", Event()
    save_speech_location(source, config)
    original = config.read_bytes()
    module = no_runtimes(monkeypatch)
    if failure == "corrupt":
        (source / "models/model/v1/model.onnx").write_bytes(b"corrupt")
    elif failure == "runtime":
        monkeypatch.setattr(module, "_prepare", lambda *args: (_ for _ in ()).throw(RuntimeError("probe failed")))
    elif failure == "save":
        monkeypatch.setattr(module, "save_speech_location", lambda *args: (_ for _ in ()).throw(OSError("save failed")))
    on_stage = (lambda stage: cancel.set()) if failure == "cancel" else None
    with pytest.raises((DownloadCancelled, RuntimeError, OSError)):
        migrate_storage(source, target, config, cancel=cancel, on_stage=on_stage)
    assert config.read_bytes() == original
    assert load_speech_location(config) == source
    assert (source / "models/model/v1/model.onnx").is_file()
    assert not (source / ".storage-moved.json").exists()
    assert set(item.name for item in target.iterdir()) <= {".storage.lock"}


def test_missing_and_uncommitted_move_marker_does_not_retire_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    config = tmp_path / "location.json"
    save_speech_location(source, config)
    atomic_json(source / ".storage-moved.json", {
        "destination": str(tmp_path / "uncommitted"), "config_path": str(config),
        "transaction": "prepared-not-committed",
    })
    with storage_lease(source):
        assert json.loads(config.read_text())["speech_directory"] == str(source)


def test_first_location_can_be_chosen_before_any_model_is_downloaded(tmp_path):
    source, target = tmp_path / "not-created", tmp_path / "selected"
    plan = preview_migration(source, target)
    assert plan.copy_bytes == 0 and not source.exists() and not target.exists()
    config = tmp_path / "location.json"
    migrate_storage(source, target, config)
    assert load_speech_location(config) == target


def test_report_audio_path_moves_without_changing_measurement_identity(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    no_runtimes(monkeypatch)
    (source / "reports").mkdir()
    (source / "reports/voice.wav").write_bytes(b"audio")
    identity = {"fingerprint": "unchanged", "voice_id": "voice-1"}
    atomic_json(source / "reports/result.json", {
        "preview": str(source / "reports/voice.wav"), "model_identities": identity,
    })
    migrate_storage(source, target, tmp_path / "location.json")
    migrated = json.loads((target / "reports/result.json").read_text())
    assert migrated["preview"] == str(target / "reports/voice.wav")
    assert migrated["model_identities"] == identity
    assert json.loads((source / "reports/result.json").read_text())["preview"] == str(source / "reports/voice.wav")


def test_process_killed_during_copy_leaves_owned_target_that_retry_can_resume(tmp_path):
    source, target = source_library(tmp_path), tmp_path / "target"
    config = tmp_path / "location.json"
    save_speech_location(source, config)
    code = (
        "import os,sys; from shinar.local_speech.storage_migration import migrate_storage; "
        "migrate_storage(sys.argv[1],sys.argv[2],sys.argv[3],on_stage=lambda value: os._exit(17))"
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(source), str(target), str(config)],
        capture_output=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert child.returncode == 17
    assert load_speech_location(config) == source
    assert preview_migration(source, target).resume
    partial = target / "models/model/v1/model.onnx"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b"incomplete copied bytes")
    migrate_storage(source, target, config)
    assert load_speech_location(config) == target
    assert partial.read_bytes() == (source / "models/model/v1/model.onnx").read_bytes()
    with pytest.raises(StorageMovedError):
        migrate_storage(source, target, config)


def test_insufficient_space_does_not_publish_location_or_touch_source(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    module = no_runtimes(monkeypatch)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda root: type("Disk", (), {"free": 0})())
    config = tmp_path / "location.json"
    with pytest.raises(RuntimeError, match="insufficient_space"):
        migrate_storage(source, target, config)
    assert not config.exists()
    assert not (source / ".storage-moved.json").exists()
    assert set(item.name for item in target.iterdir()) <= {".storage.lock"}


def test_unknown_source_files_are_explicitly_retained_and_never_removed(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    no_runtimes(monkeypatch)
    (source / "custom-recording.wav").write_bytes(b"personal input")
    plan = preview_migration(source, target)
    assert "custom-recording.wav" in plan.to_dict()["retainedOnly"]
    result = migrate_storage(source, target, tmp_path / "location.json")
    assert "custom-recording.wav" in result["retainedOnly"]
    assert (source / "custom-recording.wav").read_bytes() == b"personal input"


def test_corrupt_complete_download_aborts_before_location_commit(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    no_runtimes(monkeypatch)
    (source / "downloads" / ("0" * 64)).write_bytes(b"wrong digest")
    config = tmp_path / "location.json"
    with pytest.raises(RuntimeError, match="verification_failed"):
        migrate_storage(source, target, config)
    assert not config.exists()
    assert (source / "downloads" / ("0" * 64)).read_bytes() == b"wrong digest"


def test_interruption_immediately_after_atomic_commit_preserves_active_target(tmp_path, monkeypatch):
    source, target = source_library(tmp_path), tmp_path / "target"
    module = no_runtimes(monkeypatch)
    config = tmp_path / "location.json"

    def save_then_interrupt(location, path):
        save_speech_location(location, path)
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "save_speech_location", save_then_interrupt)
    result = migrate_storage(source, target, config)
    assert result["restartRequired"]
    assert load_speech_location(config) == target
    assert (target / "models/model/v1/model.onnx").is_file()
    with pytest.raises(StorageMovedError):
        with storage_lease(source):
            pytest.fail("committed source accepted writes")
