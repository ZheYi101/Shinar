"""Storage jobs stay identified and joined; QML exposes review before removal."""

import asyncio
from concurrent.futures import Future
import hashlib
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QObject, QMetaObject

from shinar.desktop.speech_library.storage_management import SpeechStorageController
from shinar.desktop.tasks.worker import AsyncWorker
from tests.support.qt import click, until


def test_inventory_is_detached_and_stale_completion_is_ignored(qt_app, tmp_path):
    async def runner(request, **kwargs):
        return {"planId": "one", "totalBytes": 100, "nested": {"items": [1]}}

    controller = SpeechStorageController(tmp_path, runner=runner)
    try:
        controller.refresh()
        until(lambda: not controller.busy)
        snapshot = controller.inventory
        snapshot["nested"]["items"].append(2)
        assert controller.inventory["nested"]["items"] == [1]
        controller._completed("expired", {"totalBytes": 0}, "")
        assert controller.inventory["totalBytes"] == 100
    finally:
        controller.close()


def test_maintenance_rejects_active_voice_and_environment_location(qt_app, tmp_path):
    calls = []

    async def runner(request, **kwargs):
        calls.append(request)
        return {"planId": "one", "reclaimableBytes": 30}

    controller = SpeechStorageController(tmp_path, available=lambda: False,
                                         location_locked=True, runner=runner)
    try:
        controller.refresh()
        until(lambda: not controller.busy)
        controller.cleanCaches()
        controller.previewMigration(str(tmp_path / "other"))
        assert len(calls) == 1
        assert "使用中" in controller.status
        assert not controller.canChangeLocation
    finally:
        controller.close()


def test_migration_keeps_original_request_and_requires_restart(qt_app, tmp_path):
    calls = []

    async def runner(request, **kwargs):
        calls.append(request)
        if request.operation.endswith("preview"):
            return {"destination": str(tmp_path / "new"), "requiredBytes": 100}
        return {"restartRequired": True}

    config = tmp_path / "location.json"
    controller = SpeechStorageController(tmp_path / "old", config_path=config, runner=runner)
    try:
        controller.previewMigration((tmp_path / "new").as_uri())
        until(lambda: not controller.busy)
        detached = controller.migration
        detached["destination"] = "wrong"
        controller.migrate()
        until(lambda: not controller.busy)
        assert calls[-1].args == (str(tmp_path / "old"), str(tmp_path / "new"))
        assert calls[-1].options == {"config_path": config}
        assert controller.location == str(tmp_path / "old")
        assert controller.restartRequired
        controller.refresh()
        assert len(calls) == 2
    finally:
        controller.close()


def test_cancel_and_shutdown_wait_for_actual_job(qt_app, tmp_path):
    completed = []
    started = Event()

    async def runner(request, *, cancel, **kwargs):
        try:
            started.set()
            while not cancel.is_set():
                await asyncio.sleep(.01)
            raise RuntimeError("speech_setup_cancelled")
        finally:
            await asyncio.sleep(.03)
            completed.append(True)

    controller = SpeechStorageController(tmp_path, runner=runner)
    controller.refresh()
    until(started.is_set)
    controller.close()
    assert completed == [True]
    assert controller.finish_shutdown()
    controller._completed("late", {"totalBytes": 100}, "")
    assert not controller.inventory


def test_qml_cache_cleanup_is_explicit_and_keeps_models(library_desktop):
    app, library, vm, window, engine, tmp_path = library_desktop
    cache = library.store.root / "downloads" / hashlib.sha256(b"cache").hexdigest()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"cache")
    part = cache.with_suffix(".part")
    part.write_bytes(b"unfinished")
    model = library.store.root / "models/keep/weights"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"installed")
    controller = engine.storage_management
    try:
        click(window, "openSpeechStorage")
        page = window.findChild(QObject, "speechStoragePage")
        until(lambda: page.property("visible") and not controller.busy and bool(controller.inventory))
        assert controller.inventory["reclaimableBytes"] == 5
        click(window, "cleanSpeechCache")
        confirmation = window.findChild(QObject, "speechCacheConfirmation")
        assert confirmation.property("visible")
        assert cache.exists()
        assert QMetaObject.invokeMethod(confirmation, "accept")
        until(lambda: not controller.busy and not cache.exists())
        assert part.read_bytes() == b"unfinished"
        assert model.read_bytes() == b"installed"
        click(window, "speechSettingsBack")
        assert not page.property("visible")
    finally:
        controller.close()


def test_owned_process_scan_and_migration_use_only_injected_location(qt_app, tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    (source / "compute.json").write_text("{}")
    destination, config = tmp_path / "new", tmp_path / "location.json"
    controller = SpeechStorageController(source, config_path=config)
    try:
        controller.refresh()
        until(lambda: not controller.busy, timeout=10000)
        assert controller.inventory["totalBytes"] >= 2
        controller.previewMigration(str(destination))
        until(lambda: not controller.busy, timeout=10000)
        assert controller.migration["destination"] == str(destination)
        assert not config.exists()
        controller.migrate()
        until(lambda: not controller.busy, timeout=10000)
        assert controller.restartRequired, controller.status
        assert (destination / "compute.json").read_text() == "{}"
        assert (source / "compute.json").read_text() == "{}"
        assert config.is_file()
    finally:
        controller.close()


@pytest.mark.parametrize("operation", ["clean", "migrate"])
def test_maintenance_waits_for_actual_release_and_resumes_on_qt(qt_app, tmp_path, operation):
    released = Future()
    calls, resumed = [], []
    main_thread = get_ident()

    async def runner(request, **kwargs):
        calls.append(request.operation)
        if request.operation.endswith("scan"):
            return {"planId": "one", "reclaimableBytes": 30}
        if request.operation.endswith("preview"):
            return {"destination": str(tmp_path / "new")}
        assert released.done()
        return {}

    def release():
        assert get_ident() == main_thread
        return released

    controller = SpeechStorageController(tmp_path / "old", release=release,
                                         resume=lambda: resumed.append(get_ident()), runner=runner)
    try:
        if operation == "clean":
            controller.refresh()
        else:
            controller.previewMigration(str(tmp_path / "new"))
        until(lambda: not controller.busy)
        previous = list(calls)
        controller.cleanCaches() if operation == "clean" else controller.migrate()
        assert controller.busy and calls == previous
        released.set_result(None)
        until(lambda: not controller.busy)
        assert "speech_storage_" + operation in calls
        assert resumed == ([main_thread] if operation == "clean" else [])
        assert controller.restartRequired == (operation == "migrate")
    finally:
        controller.close()


def test_cancel_during_release_wait_does_not_start_maintenance(qt_app, tmp_path):
    released, resumed, calls = Future(), [], []

    async def runner(request, **kwargs):
        calls.append(request.operation)
        return {"planId": "one", "reclaimableBytes": 30}

    controller = SpeechStorageController(tmp_path, runner=runner, release=lambda: released,
                                         resume=lambda: resumed.append(True))
    try:
        controller.refresh()
        until(lambda: not controller.busy)
        controller.cleanCaches()
        controller.cancel()
        assert controller.busy and not released.cancelled()
        released.set_result(None)
        until(lambda: not controller.busy)
        assert calls == ["speech_storage_scan"]
        assert resumed == [True] and "取消" in controller.status
    finally:
        controller.close()


def test_shutdown_waits_for_release_completion_on_other_loop(qt_app, tmp_path):
    released = Future()

    async def runner(request, **kwargs):
        assert request.operation == "speech_storage_scan"
        return {"planId": "one", "reclaimableBytes": 30}

    controller = SpeechStorageController(tmp_path, runner=runner, release=lambda: released)
    controller.refresh()
    until(lambda: not controller.busy)
    controller.cleanCaches()
    controller.begin_shutdown()
    assert not controller.finish_shutdown() and not released.cancelled()
    released.set_result(None)
    until(controller.finish_shutdown)
    controller.close()


def test_app_handoff_releases_models_on_existing_worker(qt_app):
    from shinar.desktop.app import _release_for_storage

    entered, finish, finished = Event(), Event(), Event()
    owner_threads, frozen = [], []
    worker = AsyncWorker()

    async def release():
        owner_threads.append(get_ident())
        entered.set()
        while not finish.is_set():
            await asyncio.sleep(.01)
        finished.set()

    readiness = SimpleNamespace(setStorageMaintenance=lambda active: frozen.append((active, get_ident())))
    try:
        completion = _release_for_storage(readiness, SimpleNamespace(release=release), worker)
        until(entered.is_set)
        assert not completion.done() and not finished.is_set()
        assert frozen == [(True, get_ident())]
        assert owner_threads == [worker._thread.ident]
        finish.set()
        until(completion.done)
        completion.result()
        assert finished.is_set()
    finally:
        finish.set()
        worker.close(lambda: asyncio.sleep(0))


def test_maintenance_releases_resident_lease_before_exclusive_work(qt_app, tmp_path):
    from shinar.desktop.app import _release_for_storage
    from shinar.local_speech.storage_lease import storage_lease

    worker, entered = AsyncWorker(), Event()
    resident, order = [], []

    async def load():
        lease = storage_lease(tmp_path)
        lease.__enter__()
        resident.append(lease)
        entered.set()

    async def release():
        await asyncio.sleep(.02)
        resident.pop().__exit__(None, None, None)
        order.append("released")

    async def runner(request, **kwargs):
        if request.operation.endswith("scan"):
            return {"planId": "one", "reclaimableBytes": 30}
        with storage_lease(tmp_path, exclusive=True):
            order.append("exclusive")
        return {}

    readiness = SimpleNamespace(setStorageMaintenance=lambda active: None)
    service = SimpleNamespace(release=release)
    controller = SpeechStorageController(
        tmp_path, runner=runner, release=lambda: _release_for_storage(readiness, service, worker)
    )
    try:
        worker.submit(load)
        until(entered.is_set)
        controller.refresh()
        until(lambda: not controller.busy)
        controller.cleanCaches()
        until(lambda: not controller.busy)
        assert order == ["released", "exclusive"]
        assert "已清理" in controller.status or not controller.status
    finally:
        controller.close()
        worker.close(lambda: release() if resident else asyncio.sleep(0))
