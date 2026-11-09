from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
from threading import Thread
from types import SimpleNamespace

import pytest

from shinar.local_speech.storage_lease import storage_lease
from shinar.local_speech.usage import cached_model_bytes, storage_usage


def test_storage_snapshot_counts_copies_but_not_hard_links_or_external_links(tmp_path):
    root = tmp_path / "speech"
    for name in ("models", "downloads", "runtimes"):
        (root / name).mkdir(parents=True)
    (root / "models/model.onnx").write_bytes(b"m" * 1024**2)
    source = root / "downloads/wheel"
    source.write_bytes(b"w" * 2 * 1024**2)
    os.link(source, root / "runtimes/wheel")
    (root / "report.json").write_bytes(b"x" * 1024**2)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "not-ours").write_bytes(b"z" * 1024**2)
    try:
        (root / "external").symlink_to(outside, target_is_directory=True)
    except OSError:
        pass  # Creating Windows symlinks can require Developer Mode.
    usage = storage_usage(root)
    assert usage == {"installedMiB": 3.0, "cacheMiB": 0.0, "otherMiB": 1.0,
                     "totalMiB": 4.0, "incomplete": False}
    assert storage_usage(tmp_path / "missing")["totalMiB"] == 0.0
    assert not storage_usage(tmp_path / "missing")["incomplete"]


def test_model_cache_includes_retained_partials_and_deduplicates_assets(tmp_path):
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads/same").write_bytes(b"model")
    (tmp_path / "downloads/next.part").write_bytes(b"part")
    assets = [SimpleNamespace(sha256=name) for name in ("same", "same", "next", "absent")]
    assert cached_model_bytes(tmp_path, assets) == 9


@contextmanager
def directory_link(path, target):
    if os.name != "nt":
        path.symlink_to(target, target_is_directory=True)
    else:
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path), str(target)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    try:
        yield
    finally:
        if path.is_symlink():
            path.unlink()
        else:
            path.rmdir()


def test_accounting_excludes_directory_links_without_python312_path_api(tmp_path, monkeypatch):
    root, outside = tmp_path / "speech", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    retained = outside / "cached"
    retained.write_bytes(b"x" * 1024**2)
    monkeypatch.delattr(Path, "is_junction", raising=False)
    with directory_link(root / "downloads", outside), directory_link(root / "models", outside):
        assert cached_model_bytes(root, [SimpleNamespace(sha256="cached")]) == 0
        assert storage_usage(root) == {
            "installedMiB": 0.0, "cacheMiB": 0.0, "otherMiB": 0.0,
            "totalMiB": 0.0, "incomplete": False,
        }
        assert retained.stat().st_size == 1024**2


@pytest.mark.parametrize("child", ["", "nested"])
def test_accounting_refuses_linked_root_or_ancestor(tmp_path, monkeypatch, child):
    outside = tmp_path / "outside"
    data = outside / child / "downloads"
    data.mkdir(parents=True)
    (data / "cached").write_bytes(b"external data")
    monkeypatch.delattr(Path, "is_junction", raising=False)
    with directory_link(tmp_path / "linked", outside):
        root = tmp_path / "linked" / child
        assert cached_model_bytes(root, [SimpleNamespace(sha256="cached")]) == 0
        assert storage_usage(root)["totalMiB"] == 0
        assert storage_usage(root)["incomplete"]


def test_shared_report_cache_bytes_belong_to_retained_category(tmp_path):
    download = tmp_path / "downloads"
    download.mkdir()
    blob = download / ("a" * 64)
    blob.write_bytes(b"x" * 1024**2)
    os.link(blob, tmp_path / "benchmark.wav")
    assert storage_usage(tmp_path) == {
        "installedMiB": 0.0, "cacheMiB": 0.0, "otherMiB": 1.0,
        "totalMiB": 1.0, "incomplete": False,
    }


def test_missing_root_is_not_created_by_usage_accounting(tmp_path):
    root = tmp_path / "missing"
    assert storage_usage(root)["totalMiB"] == 0
    assert not storage_usage(root)["incomplete"]
    assert cached_model_bytes(root, [SimpleNamespace(sha256="missing")]) == 0
    assert not root.exists()


def test_unreadable_directory_preserves_partial_inventory(tmp_path, monkeypatch):
    import shinar.local_speech.storage_inventory as module

    (tmp_path / "models").mkdir()
    (tmp_path / "models/model").write_bytes(b"x" * 1024**2)
    (tmp_path / "downloads").mkdir()
    original = module.os.scandir

    def scan(path):
        if Path(path) == tmp_path / "downloads":
            raise PermissionError("unreadable test directory")
        return original(path)

    monkeypatch.setattr(module.os, "scandir", scan)
    assert storage_usage(tmp_path) == {
        "installedMiB": 1.0, "cacheMiB": 0.0, "otherMiB": 0.0,
        "totalMiB": 1.0, "incomplete": True,
    }


def test_maintenance_lease_returns_unavailable_usage_without_blocking(tmp_path):
    (tmp_path / "model").write_bytes(b"x" * 1024**2)
    result = []
    with storage_lease(tmp_path, exclusive=True):
        thread = Thread(target=lambda: result.append(storage_usage(tmp_path)))
        thread.start()
        thread.join(5)
        assert not thread.is_alive()
    assert result[0]["totalMiB"] == 0 and result[0]["incomplete"]
    assert storage_usage(tmp_path)["totalMiB"] == 1.0
