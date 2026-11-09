"""Unavailable selected storage is visible even when launched without a console."""

from pathlib import Path

import pytest

from shinar.configuration_location import SpeechStorageLocationError
from shinar.desktop.shell.startup_error import create_storage_error_engine, storage_error_message
from tests.support.qt import click, item, until


class EngineStub:
    def setInitialProperties(self, values):
        self.values = values

    def load(self, path):
        self.path = path

    def rootObjects(self):
        return [object()]


@pytest.mark.parametrize("code, expected", [
    ("speech_storage_location_unavailable", "所选语音资源位置不可用"),
    ("speech_storage_location_invalid", "存储位置配置无法读取"),
])
def test_error_engine_factory_is_injectable_and_never_touches_configuration(tmp_path, code, expected):
    config = tmp_path / "storage-location.json"
    config.write_bytes(b"preserve configuration exactly")
    engine = create_storage_error_engine(
        SpeechStorageLocationError(code), config_path=config, engine_factory=EngineStub,
    )
    assert expected in engine.values["errorMessage"]
    assert engine.values["configurationPath"] == str(config)
    assert Path(engine.path.toLocalFile()).name == "StartupError.qml"
    assert config.read_bytes() == b"preserve configuration exactly"
    assert set(tmp_path.iterdir()) == {config}


def test_error_text_gives_recovery_without_falling_back_or_showing_raw_exceptions():
    message, advice = storage_error_message(SpeechStorageLocationError("speech_storage_location_unavailable"))
    assert "不可用" in message and "磁盘" in advice and "重新打开" in advice
    assert "speech_storage" not in message + advice


def test_independent_qml_error_window_loads_and_exits_without_a_viewmodel(qt_app, tmp_path):
    config = tmp_path / "未连接的模型磁盘/storage-location.json"
    engine = create_storage_error_engine(
        SpeechStorageLocationError("speech_storage_location_unavailable"), config_path=config,
    )
    window = engine.rootObjects()[0]
    try:
        until(lambda: window.isVisible())
        assert "不可用" in item(window, "storageStartupErrorMessage").property("text")
        assert item(window, "storageStartupConfigurationPath").property("text") == str(config)
        assert item(window, "storageStartupExit").property("text") == "退出"
        for width in (360, 560):
            window.setWidth(width)
            qt_app.processEvents()
            assert item(window, "storageStartupConfigurationPath").width() >= 300
        click(window, "storageStartupExit")
        until(lambda: not window.isVisible())
        assert not config.parent.exists()
    finally:
        window.close()
        engine.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize("failure", ["unavailable", "invalid"])
def test_main_shows_storage_failure_before_opening_any_learning_store(tmp_path, monkeypatch, failure):
    import shinar.configuration_location as location
    from shinar.desktop import app
    from shinar.desktop.shell import identity, startup_error

    config = tmp_path / "storage-location.json"
    selected = tmp_path / "external-model-drive"
    selected.mkdir()
    location.save_speech_location(selected, config)
    if failure == "unavailable":
        selected.rmdir()
    else:
        config.write_text("invalid configuration", encoding="utf-8")
    original = config.read_bytes()
    monkeypatch.setattr(location, "location_file", lambda value=None: config)
    for key in ("SHINAR_DATA_DIR", "LINGUALOOP_DATA_DIR", "SHINAR_SPEECH_DIR", "LINGUALOOP_SPEECH_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(app, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setattr(identity, "set_windows_app_id", lambda: None)
    monkeypatch.setattr(app, "create_workbench", lambda **kwargs: pytest.fail("learning store opened"))
    monkeypatch.setattr(app, "create_engine", lambda *args: pytest.fail("main engine constructed"))

    class ApplicationStub:
        def __init__(self, argv):
            self.argv = argv

        def exec(self):
            pytest.fail("main event loop started")

    monkeypatch.setattr(app, "_load_qt", lambda: {"QApplication": ApplicationStub})
    shown = []

    def show(error, *, app):
        shown.append((str(error), app.argv))
        return 73

    monkeypatch.setattr(startup_error, "show_storage_startup_error", show)
    assert app.main(["--real"]) == 73
    assert shown == [("speech_storage_location_" + failure, ["shinar-desktop", "--real"])]
    assert config.read_bytes() == original
    assert not list(tmp_path.rglob("*.sqlite3"))
