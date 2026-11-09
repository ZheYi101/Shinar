"""Explicit RTC preparation reuses pinned bytes without moving old environments."""

import hashlib
import os
from pathlib import Path
import subprocess
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from shinar.local_speech.catalog import Artifact
from shinar.local_speech.downloads import DownloadCancelled, ModelStore
from shinar.realtime.storage_upgrade import reuse_legacy_assets


def artifact(path, data, **extra):
    return Artifact(path=path, url="https://example.test/" + path,
                    sha256=hashlib.sha256(data).hexdigest(), size=len(data), **extra)


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def pinned(monkeypatch):
    import shinar.realtime.storage_upgrade as module

    bodies = {"dependency.whl": b"pinned wheel", "python.tar.gz": b"pinned python",
              "uv.zip": b"pinned bootstrap", "vad.onnx": b"pinned vad", "server.zip": b"pinned server"}
    assets = {name: artifact(name, body) for name, body in bodies.items()}
    assets["python.tar.gz"] = artifact("python.tar.gz", bodies["python.tar.gz"],
                                       archive_root="python", unpacked_limit=1024)
    package = lambda name, file: SimpleNamespace(id=name, revision="pinned", files=[assets[file]],
                                                  fingerprint=name, required_files=[file])
    monkeypatch.setattr(module, "runtime_spec", lambda name: SimpleNamespace(
        wheels=(assets["dependency.whl"].model_dump(),), resources=(), fingerprint="rtc-pinned"))
    monkeypatch.setattr(module, "resource_package", lambda name: package("python", "python.tar.gz"))
    monkeypatch.setattr(module, "manifest", lambda: {"uv": assets["uv.zip"].model_dump()})
    monkeypatch.setattr(module, "VAD_PACKAGE", package("vad", "vad.onnx"))
    monkeypatch.setattr(module, "server_package", lambda: package("server", "server.zip"))
    return assets, bodies


def test_reuses_only_verified_known_blobs_wheels_and_raw_assets(tmp_path, pinned):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    locations = {
        "dependency.whl": "wheelhouses/rtc-pinned/dependency.whl",
        "python.tar.gz": "downloads/" + assets["python.tar.gz"].sha256,
        "uv.zip": "downloads/" + assets["uv.zip"].sha256,
        "vad.onnx": "models/vad/pinned/vad.onnx",
        "server.zip": "sfu/server.zip",
    }
    for name, relative in locations.items():
        put(source, relative, bodies[name])
    put(source, "runtimes/old/Scripts/python.exe", b"never copied")
    put(source, "library.sqlite3", b"private")
    put(source, "downloads/" + "0" * 64, b"unknown")
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()}
    result = reuse_legacy_assets(source, target)
    assert result == {"completedFiles": 5, "completedBytes": sum(map(len, bodies.values())),
                      "partialFiles": 0, "partialBytes": 0}
    for name, item in assets.items():
        assert (target / "downloads" / item.sha256).read_bytes() == bodies[name]
    assert all((source / path).read_bytes() == data for path, data in before.items())
    assert not (target / "runtimes").exists() and not (target / "models").exists()
    assert not (target / "library.sqlite3").exists()
    assert not (target / "downloads" / ("0" * 64)).exists()
    assert reuse_legacy_assets(source, target)["completedFiles"] == 0


def test_corrupt_and_wrong_revision_candidates_are_not_published(tmp_path, pinned):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item = assets["dependency.whl"]
    put(source, "downloads/" + item.sha256, b"x" * item.size)
    put(source, "wheelhouses/other-revision/dependency.whl", bodies[item.path])
    put(source, "downloads/" + assets["uv.zip"].sha256, b"too large" * 10)
    result = reuse_legacy_assets(source, target)
    assert not any(result.values())
    assert not list((target / "downloads").iterdir())


@pytest.mark.parametrize("existing", [b"a", b"larger existing partial"])
def test_partial_reuse_keeps_larger_target_and_source_untouched(tmp_path, pinned, existing):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item = assets["dependency.whl"]
    name = "downloads/" + item.sha256 + ".part"
    original = bodies[item.path][:5]
    old = put(source, name, original)
    current = put(target, name, existing)
    result = reuse_legacy_assets(source, target)
    expected = original if len(original) > len(existing) else existing
    assert current.read_bytes() == expected and old.read_bytes() == original
    assert result["partialFiles"] == (len(original) > len(existing))
    assert not (target / "downloads" / item.sha256).exists()


def test_verified_target_is_retained_and_invalid_complete_target_can_be_repaired(tmp_path, pinned):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item = assets["dependency.whl"]
    name = "downloads/" + item.sha256
    put(source, name, bodies[item.path])
    current = put(target, name, bodies[item.path])
    identity = current.stat().st_ino
    assert not any(reuse_legacy_assets(source, target).values())
    assert current.stat().st_ino == identity
    current.write_bytes(b"corrupt")
    assert reuse_legacy_assets(source, target)["completedFiles"] == 1
    assert current.read_bytes() == bodies[item.path]


@pytest.mark.parametrize("valid_prefix", [True, False])
def test_reused_partial_still_requires_full_final_download_sha(tmp_path, pinned, valid_prefix):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item, body = assets["dependency.whl"], bodies["dependency.whl"]
    put(source, "downloads/" + item.sha256 + ".part", body[:4] if valid_prefix else b"evil")
    assert reuse_legacy_assets(source, target)["partialBytes"] == 4

    def serve(request):
        assert request.headers["Range"] == "bytes=4-"
        return httpx.Response(206, headers={"Content-Range": f"bytes 4-{len(body)-1}/{len(body)}"},
                              content=body[4:])

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        store = ModelStore(target)
        if valid_prefix:
            assert store._fetch(item, client, None, lambda *_: None).read_bytes() == body
        else:
            with pytest.raises(ValueError, match="校验失败"):
                store._fetch(item, client, None, lambda *_: None)
            assert not (target / "downloads" / item.sha256).exists()


@pytest.mark.parametrize("interruption", ["cancel", "write-failure", "source-replaced"])
def test_interrupted_copy_does_not_publish_or_leave_temporary_files(tmp_path, pinned, monkeypatch, interruption):
    import shinar.realtime.storage_upgrade as module

    assets, bodies = pinned
    source, target, cancel = tmp_path / "legacy", tmp_path / "selected", Event()
    item = assets["dependency.whl"]
    original = put(source, "downloads/" + item.sha256, bodies[item.path])
    actual_fsync = os.fsync
    actual_info, checks = module._file_info, []

    def flush(descriptor):
        actual_fsync(descriptor)
        if interruption == "cancel":
            cancel.set()

    def info(path):
        if interruption == "source-replaced" and path == original:
            checks.append(True)
            if len(checks) == 2:
                replacement = put(source, "replacement", bodies[item.path])
                os.replace(replacement, original)
        return actual_info(path)

    monkeypatch.setattr(module.os, "fsync", flush)
    monkeypatch.setattr(module, "_file_info", info)
    if interruption == "write-failure":
        monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk failed")))
    expected = DownloadCancelled if interruption == "cancel" else (OSError if interruption == "write-failure" else RuntimeError)
    with pytest.raises(expected):
        reuse_legacy_assets(source, target, cancel=cancel)
    assert original.read_bytes() == bodies[item.path]
    assert not list((target / "downloads").iterdir())


def test_missing_root_and_pre_cancelled_request_do_not_create_target(tmp_path, pinned):
    source, target = tmp_path / "missing", tmp_path / "selected"
    assert not any(reuse_legacy_assets(source, target).values())
    cancel = Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        reuse_legacy_assets(source, target, cancel=cancel)
    assert not source.exists() and not target.exists()


@pytest.mark.parametrize("side", ["source", "target"])
def test_rejects_junction_ancestors_even_on_python_311(tmp_path, pinned, side):
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    source, target, outside = tmp_path / "legacy", tmp_path / "selected", tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    linked = source / "downloads" if side == "source" else target
    subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                   check=True, capture_output=True)
    with pytest.raises(ValueError, match="speech_storage_link_unsupported"):
        reuse_legacy_assets(source, target)
    assert not list(outside.iterdir())


def test_rejects_reparse_leaf_before_opening_it(tmp_path, pinned, monkeypatch):
    import shinar.realtime.storage_upgrade as module

    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item = assets["dependency.whl"]
    leaf = put(source, "downloads/" + item.sha256, bodies[item.path])
    identity, original = leaf.stat().st_ino, module.is_reparse
    monkeypatch.setattr(module, "is_reparse", lambda info: info.st_ino == identity or original(info))
    with pytest.raises(ValueError, match="speech_storage_link_unsupported"):
        reuse_legacy_assets(source, target)
    assert not list((target / "downloads").iterdir())


def test_installed_target_resource_does_not_recreate_its_archive_cache(tmp_path, pinned, monkeypatch):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item = assets["python.tar.gz"]
    put(source, "downloads/" + item.sha256, bodies[item.path])
    put(source, "downloads/" + item.sha256 + ".part", b"part")
    actual = ModelStore.installed
    monkeypatch.setattr(ModelStore, "installed", lambda self, package: (
        True if package.id == "python" and self.root == target else actual(self, package)))
    result = reuse_legacy_assets(source, target)
    assert not any(result.values())
    assert not list((target / "downloads").iterdir())


@pytest.mark.parametrize("valid", [True, False])
def test_existing_target_wheelhouse_is_hashed_before_omitting_download(tmp_path, pinned, valid):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    item, body = assets["dependency.whl"], bodies["dependency.whl"]
    put(source, "downloads/" + item.sha256, body)
    current = put(target, "wheelhouses/rtc-pinned/dependency.whl", body if valid else b"x" * len(body))
    result = reuse_legacy_assets(source, target)
    assert result["completedFiles"] == (not valid)
    assert current.read_bytes() == (body if valid else b"x" * len(body))
    assert (target / "downloads" / item.sha256).exists() == (not valid)


@pytest.mark.parametrize("name,relative", [("vad.onnx", "models/vad/pinned/vad.onnx"),
                                          ("server.zip", "sfu/server.zip")])
def test_existing_target_raw_assets_do_not_recreate_download_cache(tmp_path, pinned, name, relative):
    assets, bodies = pinned
    source, target = tmp_path / "legacy", tmp_path / "selected"
    put(source, "downloads/" + assets[name].sha256, bodies[name])
    put(target, relative, bodies[name])
    assert not any(reuse_legacy_assets(source, target).values())
    assert not list((target / "downloads").iterdir())
