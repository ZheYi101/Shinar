"""A committed location wins over cancellation of its late acknowledgement."""

import asyncio

import pytest

from shinar.configuration_location import load_speech_location, save_speech_location
from shinar.desktop.speech_library.storage_management import SpeechStorageController
from tests.support.qt import until


@pytest.mark.parametrize("error", ["cancel", "background_process_exited"])
def test_late_migration_error_reconciles_durable_location(qt_app, tmp_path, error):
    source, destination = tmp_path / "original", tmp_path / "new-location"
    source.mkdir()
    destination.mkdir()
    config = tmp_path / "storage-location.json"
    save_speech_location(source, config)

    async def runner(request, *, cancel, **kwargs):
        if request.operation.endswith("preview"):
            return {"destination": str(destination), "requiredBytes": 0}
        assert request.operation.endswith("migrate")
        save_speech_location(destination, config)
        # The child has committed, but the result has not reached the Qt adapter.
        while not cancel.is_set():
            await asyncio.sleep(.005)
        if error == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError(error)

    controller = SpeechStorageController(source, config_path=config, runner=runner)
    try:
        controller.previewMigration(str(destination))
        until(lambda: not controller.busy)
        controller.migrate()
        until(lambda: load_speech_location(config) == destination)
        assert controller.busy
        controller.cancel()
        until(lambda: not controller.busy)
        assert controller.restartRequired
        assert not controller.canChangeLocation
        assert controller.location == str(source)
        assert load_speech_location(config) == destination
        assert "取消" not in controller.status
    finally:
        controller.close()
