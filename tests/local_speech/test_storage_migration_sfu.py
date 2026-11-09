"""Relocation carries pinned RTC assets and rebuilds disposable SFU output offline."""

import hashlib
import io
import json
from pathlib import Path
import shutil
from threading import Event
from types import SimpleNamespace
import zipfile

import pytest

from shinar.configuration_location import load_speech_location, save_speech_location
from shinar.local_speech.catalog import Artifact
from shinar.local_speech.downloads import DownloadCancelled, ModelStore
from shinar.local_speech.storage import atomic_json
from shinar.local_speech.storage_migration import migrate_storage, preview_migration


@pytest.fixture
def sfu_library(tmp_path, monkeypatch):
    import shinar.local_speech.storage_migration as migration
    import shinar.realtime.continuous_assets as assets
    import shinar.realtime.local_server as server

    original = migration.manifest()
    monkeypatch.setattr(migration, "manifest", lambda: {**original, "runtimes": {}})
    output = io.BytesIO()
    executable = b"pinned test executable, never run"
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("livekit-server.exe", executable)
    archive = output.getvalue()
    monkeypatch.setattr(server, "ARCHIVE_NAME", "livekit_test_windows_amd64.zip")
    monkeypatch.setattr(server, "ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(server, "SERVER_VERSION", "1.2.3")
    monkeypatch.setattr(server, "RELEASE_URL", "https://example.org/livekit-test.zip")
    artifacts = [Artifact(path=name, url="https://example.org/" + name, size=len(content),
                          sha256=hashlib.sha256(content).hexdigest())
                 for name, content in (("silero_vad.onnx", b"vad"), ("LICENSE", b"license"))]
    package = assets.VAD_PACKAGE.model_copy(update={"revision": "test", "files": artifacts})
    monkeypatch.setattr(assets, "VAD_PACKAGE", package)
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "sfu").mkdir(parents=True)
    (source / "sfu" / server.ARCHIVE_NAME).write_bytes(archive)
    folder = ModelStore(source).model_path(package)
    folder.mkdir(parents=True)
    for artifact, content in zip(artifacts, (b"vad", b"license")):
        (folder / artifact.path).write_bytes(content)
    atomic_json(folder / ".installed.json", {
        "fingerprint": package.fingerprint,
        "files": {artifact.path: {"size": artifact.size, "sha256": artifact.sha256}
                  for artifact in artifacts},
    })

    def refuse_download(*args, **kwargs):
        raise AssertionError("SFU relocation must not install or download assets")

    monkeypatch.setattr(ModelStore, "install", refuse_download)
    return SimpleNamespace(source=source, target=target, archive=archive, executable=executable,
                           server=server, assets=assets, migration=migration,
                           config=tmp_path / "location.json")


def test_pinned_archive_and_vad_move_but_sfu_executable_is_rebuilt(sfu_library):
    case = sfu_library
    server_dir = case.source / "sfu/server-1.2.3"
    server_dir.mkdir()
    (server_dir / "livekit-server.exe").write_bytes(b"replaced executable")
    retained = {
        "sfu/server-secrets.json": b'{"secret":"synthetic-test-value"}',
        "sfu/debug.log": b"retained log",
        "sfu/archive.preparing": b"partial archive",
        "sfu/unknown.exe": b"unrecognized executable",
    }
    for relative, content in retained.items():
        (case.source / relative).write_bytes(content)
    assert case.assets.prepared_assets(case.source)
    plan = preview_migration(case.source, case.target)
    archive = "sfu/" + case.server.ARCHIVE_NAME
    assert [item.relative for item in plan.files if item.relative.startswith("sfu/")] == [archive]
    assert set(retained) | {"sfu/server-1.2.3"} <= set(plan.retained_only)
    assert plan.required_bytes >= plan.copy_bytes + len(case.executable) + 64 * 1024**2
    result = migrate_storage(case.source, case.target, case.config)
    assert load_speech_location(case.config) == case.target
    assert case.assets.prepared_assets(case.target)
    assert (case.target / archive).read_bytes() == case.archive
    assert (case.target / "sfu/server-1.2.3/livekit-server.exe").read_bytes() == case.executable
    assert (server_dir / "livekit-server.exe").read_bytes() == b"replaced executable"
    assert set(retained) <= set(result["retainedOnly"])
    for relative, content in retained.items():
        assert not (case.target / relative).exists()
        assert (case.source / relative).read_bytes() == content
    packages = {(package.id, package.revision) for package in case.migration._managed_packages()}
    assert (case.assets.VAD_PACKAGE.id, "test") in packages
    assert ("livekit-server", "1_2_3") in packages


def test_corrupt_sfu_archive_refuses_commit_and_preserves_original_location(sfu_library):
    case = sfu_library
    save_speech_location(case.source, case.config)
    original_config = case.config.read_bytes()
    archive = case.source / "sfu" / case.server.ARCHIVE_NAME
    archive.write_bytes(b"x" * len(case.archive))
    with pytest.raises(RuntimeError, match="verification_failed"):
        migrate_storage(case.source, case.target, case.config)
    assert archive.read_bytes() == b"x" * len(case.archive)
    assert case.config.read_bytes() == original_config
    assert not (case.source / ".storage-moved.json").exists()
    assert not case.target.exists()


def owned_resume_target(case):
    plan = preview_migration(case.source, case.target)
    case.target.mkdir()
    atomic_json(case.target / ".storage-migration.json", case.migration._journal(plan, case.config))
    for item in plan.files:
        target = case.target / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(case.source / item.relative, target)
    executable = case.target / "sfu/server-1.2.3/livekit-server.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"partial or replaced generated executable")
    return executable


def test_resume_accepts_only_pinned_generated_executable_and_rebuilds_it(sfu_library):
    case = sfu_library
    executable = owned_resume_target(case)
    assert preview_migration(case.source, case.target).resume
    migrate_storage(case.source, case.target, case.config)
    assert executable.read_bytes() == case.executable
    assert case.assets.prepared_assets(case.target)


def test_cancel_before_sfu_rebuild_rolls_back_without_changing_location(sfu_library):
    case = sfu_library
    save_speech_location(case.source, case.config)
    cancel = Event()
    with pytest.raises(DownloadCancelled, match="speech_setup_cancelled"):
        migrate_storage(case.source, case.target, case.config, cancel=cancel,
                        on_stage=lambda stage: cancel.set() if stage == "verify" else None)
    assert load_speech_location(case.config) == case.source
    assert set(path.name for path in case.target.iterdir()) <= {".storage.lock"}
    assert not (case.source / ".storage-moved.json").exists()
    assert case.assets.prepared_assets(case.source)


@pytest.mark.parametrize("relative", ["server-secrets.json", "debug.log", "unknown.exe",
                                    "server-1.2.3/unknown.exe", "unknown-directory"])
def test_resume_rejects_unknown_sfu_files_and_directories_without_deleting_them(sfu_library, relative):
    case = sfu_library
    owned_resume_target(case)
    unknown = case.target / "sfu" / relative
    if relative == "unknown-directory":
        unknown.mkdir()
    else:
        unknown.write_bytes(b"must remain untouched")
    with pytest.raises(ValueError, match="destination_not_empty"):
        migrate_storage(case.source, case.target, case.config)
    assert unknown.exists()
    assert not case.config.exists()
    assert not (case.source / ".storage-moved.json").exists()
    assert json.loads((case.target / ".storage-migration.json").read_text())["source"] == str(case.source)


@pytest.mark.parametrize("kind", ["custom", "archive-name"])
def test_unrecognized_sfu_tree_without_pinned_archive_is_retained_only(tmp_path, monkeypatch, kind):
    import shinar.local_speech.storage_migration as module

    original = module.manifest()
    monkeypatch.setattr(module, "manifest", lambda: {**original, "runtimes": {}})
    source, target = tmp_path / "source", tmp_path / "target"
    name = "custom" if kind == "custom" else Path(module._sfu_relative_paths()[0]).name
    unknown = source / "sfu" / name
    unknown.mkdir(parents=True)
    (unknown / "personal.txt").write_bytes(b"not a pinned server asset")
    plan = preview_migration(source, target)
    assert plan.files == ()
    assert plan.retained_only == ("sfu/" + name,)
    migrate_storage(source, target, tmp_path / "location.json")
    assert not (target / "sfu").exists()
    assert (unknown / "personal.txt").read_bytes() == b"not a pinned server asset"
