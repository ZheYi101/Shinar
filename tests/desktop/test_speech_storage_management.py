"""Storage jobs stay identified and joined; QML exposes review before removal."""

import asyncio
import hashlib
from threading import Event

from PySide6.QtCore import QObject, QMetaObject

from shinar.desktop.speech_library.storage_management import SpeechStorageController
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
