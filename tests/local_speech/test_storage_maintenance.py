from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from shinar.local_speech.downloads import DownloadCancelled, package_lock
from shinar.local_speech.storage_cleanup import (
    StoragePlanChangedError, clean_storage, plan_cleanup,
)
from shinar.local_speech.storage_inventory import scan_storage
from shinar.local_speech.storage_lease import (
    StorageBusyError, StorageCancelledError, StorageMovedError, storage_lease,
)


def put(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@contextmanager
def child_lease(root, *, exclusive=False):
    code = (
        "import sys; from pathlib import Path; "
        "from shinar.local_speech.storage_lease import storage_lease; "
        "lease=storage_lease(Path(sys.argv[1]),exclusive=sys.argv[2]=='True'); "
        "lease.__enter__(); print('ready',flush=True); sys.stdin.read(1); lease.__exit__(None,None,None)"
    )
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2] / "src"))
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", code, str(root), str(exclusive)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        assert process.stdout.readline().strip() == "ready", process.stderr.read()
        yield process
    finally:
        process.communicate("x", timeout=10)
        assert process.returncode == 0


def test_shared_operations_coexist_and_exclusive_maintenance_is_cross_process(tmp_path):
    root = tmp_path / "speech"
    with child_lease(root):
        with storage_lease(root):
            with package_lock(root, SimpleNamespace(id="other-model")):
                pass
        with pytest.raises(StorageBusyError, match="speech_storage_busy"):
            with storage_lease(root, exclusive=True):
                pytest.fail("maintenance entered an active root")
    with child_lease(root, exclusive=True):
        with pytest.raises(StorageBusyError):
            with package_lock(root, SimpleNamespace(id="model")):
                pytest.fail("new work entered maintenance")


def test_exclusive_owner_can_prepare_models_and_cannot_upgrade_shared_lease(tmp_path):
    with storage_lease(tmp_path, exclusive=True):
        with storage_lease(tmp_path, exclusive=True):
            with package_lock(tmp_path, SimpleNamespace(id="nested")):
                with storage_lease(tmp_path):
                    pass
    with storage_lease(tmp_path):
        with pytest.raises(StorageBusyError, match="speech_storage_busy"):
            with storage_lease(tmp_path, exclusive=True):
                pytest.fail("shared lease upgraded")


def test_resident_stt_tts_leases_can_be_released_in_non_lifo_order(tmp_path):
    first = package_lock(tmp_path, SimpleNamespace(id="resident-stt"))
    second = package_lock(tmp_path, SimpleNamespace(id="resident-tts"))
    first.__enter__()
    second.__enter__()
    first.__exit__(None, None, None)
    errors = []

    def attempt():
        try:
            with storage_lease(tmp_path, exclusive=True):
                errors.append("exclusive entered while TTS remained resident")
        except StorageBusyError:
            pass

    thread = Thread(target=attempt)
    thread.start()
    thread.join(5)
    assert not thread.is_alive() and not errors
    second.__exit__(None, None, None)
    with storage_lease(tmp_path, exclusive=True):
        pass


def test_transferred_lease_release_does_not_corrupt_owner_thread_registry(tmp_path):
    first, second = storage_lease(tmp_path), storage_lease(tmp_path)
    first.__enter__()
    second.__enter__()
    thread = Thread(target=lambda: first.__exit__(None, None, None))
    thread.start()
    thread.join(5)
    assert not thread.is_alive()
    with pytest.raises(StorageBusyError, match="speech_storage_busy"):
        with storage_lease(tmp_path, exclusive=True):
            pytest.fail("remaining shared lease was forgotten")
    second.__exit__(None, None, None)
    with storage_lease(tmp_path, exclusive=True):
        pass


def test_shared_lease_lifetime_excludes_another_thread(tmp_path):
    errors, ready, release = [], Event(), Event()

    def owner():
        try:
            with package_lock(tmp_path, SimpleNamespace(id="running")):
                ready.set()
                release.wait(5)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=owner)
    thread.start()
    try:
        assert ready.wait(5)
        with pytest.raises(StorageBusyError):
            with storage_lease(tmp_path, exclusive=True):
                pytest.fail("another thread owns the root")
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and not errors


def test_waiting_for_maintenance_can_be_cancelled_without_touching_cache(tmp_path):
    blob = put(tmp_path, "downloads/" + "a" * 64, b"original")
    cancel = Event()
    with child_lease(tmp_path, exclusive=True):
        with pytest.raises(StorageCancelledError):
            with storage_lease(tmp_path, wait=True, cancel=cancel, on_wait=cancel.set):
                pytest.fail("cancelled waiter entered")
        cancel.clear()
        with pytest.raises(DownloadCancelled):
            with package_lock(tmp_path, SimpleNamespace(id="cancelled"), wait=True,
                              cancel=cancel, on_wait=cancel.set):
                pytest.fail("cancelled package entered")
    assert blob.read_bytes() == b"original"


def test_prepared_retirement_marker_only_blocks_after_location_commit(tmp_path):
    root, destination = tmp_path / "old", tmp_path / "new"
    root.mkdir()
    config = tmp_path / "location.json"
    config.write_text(json.dumps({"speech_directory": str(root)}))
    (root / ".storage-moved.json").write_text(json.dumps({
        "destination": str(destination), "config_path": str(config), "transaction": "test",
    }))
    with storage_lease(root):
        pass
    config.write_text(json.dumps({"speech_directory": str(destination)}))
    with pytest.raises(StorageMovedError) as raised:
        with storage_lease(root):
            pytest.fail("retired root accepted new work")
    assert raised.value.destination == str(destination)
    with storage_lease(root, exclusive=True):
        with package_lock(root, SimpleNamespace(id="migration-owner")):
            pass


def test_inventory_deduplicates_installed_links_and_combined_cache_candidates(tmp_path):
    installed = put(tmp_path, "runtimes/current/pkg", b"i" * 11)
    installer = put(tmp_path, "installer-cache/pkg", b"replace")
    installer.unlink()
    os.link(installed, installer)
    blob = put(tmp_path, "downloads/" + "a" * 64, b"b" * 13)
    wheel = put(tmp_path, "wheelhouses/runtime/wheel.whl", b"replace")
    wheel.unlink()
    os.link(blob, wheel)
    put(tmp_path, "models/model.onnx", b"m" * 17)
    put(tmp_path, "downloads/" + "b" * 64 + ".part", b"p" * 19)
    put(tmp_path, "downloads/unrecognized", b"u" * 23)
    put(tmp_path, "reports/report.json", b"r" * 29)
    inventory = scan_storage(tmp_path)
    assert inventory.total_bytes == 11 + 13 + 17 + 19 + 23 + 29
    assert inventory.installed_bytes == 28
    assert inventory.cache_bytes == 55
    assert inventory.other_bytes == 29
    assert inventory.reclaimable_bytes == 13
    assert not inventory.incomplete and not inventory.excluded
    assert inventory.to_dict()["planId"] == inventory.plan_id
    assert inventory.to_dict()["logicalEstimate"] is True
    assert sum(group.unique_bytes for group in inventory.categories) > inventory.total_bytes
    with pytest.raises(FrozenInstanceError):
        inventory.files[0].size = 0
    inventory.to_dict()["categories"].clear()
    assert inventory.categories


def test_external_hardlink_bytes_are_not_advertised_as_reclaimable(tmp_path):
    root = tmp_path / "speech"
    blob = put(root, "downloads/" + "c" * 64, b"shared")
    outside = tmp_path / "outside"
    os.link(blob, outside)
    inventory = scan_storage(root)
    assert inventory.total_bytes == 6 and inventory.reclaimable_bytes == 0
    result = clean_storage(root, inventory.plan_id)
    assert result["reclaimedBytes"] == 0 and result["deletedFiles"] == 1
    assert outside.read_bytes() == b"shared"


def test_cleanup_removes_only_reviewed_complete_cache_and_preserves_running_models(tmp_path):
    put(tmp_path, "models/resource-python/python.exe", b"python")
    installed = put(tmp_path, "runtimes/current/library", b"runtime")
    shared = put(tmp_path, "installer-cache/archive/library", b"replace")
    shared.unlink()
    os.link(installed, shared)
    put(tmp_path, "downloads/" + "a" * 64, b"cache")
    put(tmp_path, "wheelhouses/one/wheel.whl", b"wheel")
    partial = put(tmp_path, "downloads/" + "b" * 64 + ".part", b"partial")
    unknown = put(tmp_path, "downloads/README.txt", b"user-notes")
    report = put(tmp_path, "reports/benchmark.json", b"report")
    plan = plan_cleanup(tmp_path)
    assert plan.reclaimable_bytes == 10 and len(plan.files) == 3
    result = clean_storage(tmp_path, plan.id)
    assert result["deletedFiles"] == 3 and result["reclaimedBytes"] == 10
    assert installed.read_bytes() == b"runtime"
    assert partial.read_bytes() == b"partial" and unknown.read_bytes() == b"user-notes"
    assert report.read_bytes() == b"report"
    assert not (tmp_path / "wheelhouses").exists()
    assert scan_storage(tmp_path).reclaimable_bytes == 0


@pytest.mark.parametrize("change", ["content", "replace", "new-file", "external-link"])
def test_stale_cleanup_plan_refuses_before_deleting_any_file(tmp_path, change):
    blob = put(tmp_path, "downloads/" + "a" * 64, b"one")
    retained = put(tmp_path, "downloads/" + "b" * 64, b"two")
    plan = plan_cleanup(tmp_path)
    if change == "content":
        blob.write_bytes(b"different")
    elif change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"one")
        os.replace(replacement, blob)
    elif change == "new-file":
        put(tmp_path, "installer-cache/new", b"new")
    else:
        os.link(blob, tmp_path.parent / (tmp_path.name + "-external"))
    with pytest.raises(StoragePlanChangedError, match="speech_storage_plan_changed"):
        clean_storage(tmp_path, plan.id)
    assert blob.exists() and retained.read_bytes() == b"two"


def test_cleanup_while_an_operation_runs_is_busy_and_cancel_is_non_destructive(tmp_path):
    blob = put(tmp_path, "downloads/" + "a" * 64, b"cache")
    plan = plan_cleanup(tmp_path)
    with child_lease(tmp_path):
        with pytest.raises(StorageBusyError):
            clean_storage(tmp_path, plan.id)
    cancel = Event()
    cancel.set()
    with pytest.raises(StorageCancelledError):
        clean_storage(tmp_path, plan.id, cancel=cancel)
    assert blob.read_bytes() == b"cache"


def test_inventory_does_not_create_missing_storage(tmp_path):
    root = tmp_path / "missing"
    assert scan_storage(root).total_bytes == 0
    assert not root.exists()


def test_inventory_and_cleanup_do_not_follow_external_directory_links(tmp_path):
    root = tmp_path / "speech"
    outside = tmp_path / "outside"
    secret = put(outside, "keep", b"not-owned")
    put(root, "downloads/" + "a" * 64, b"cache")
    link = root / "wheelhouses"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    inventory = scan_storage(root)
    assert inventory.total_bytes == 5 and inventory.excluded == ("wheelhouses",)
    clean_storage(root, inventory.plan_id)
    assert secret.read_bytes() == b"not-owned" and link.is_dir()
    with pytest.raises(ValueError, match="link_unsupported"):
        scan_storage(link / "child")


def test_inventory_change_to_junction_rejects_cleanup_and_retains_external_files(tmp_path):
    root = tmp_path / "speech"
    outside = tmp_path / "outside"
    secret = put(outside, "keep", b"not-owned")
    put(root, "wheelhouses/empty", b"cache")
    plan = plan_cleanup(root)
    (root / "wheelhouses/empty").unlink()
    (root / "wheelhouses").rmdir()
    link = root / "wheelhouses"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    with pytest.raises(StoragePlanChangedError):
        clean_storage(root, plan.id)
    assert secret.read_bytes() == b"not-owned"
