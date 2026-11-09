"""A minimal visible startup failure without loading a learning library or facade."""

from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from shinar.configuration_location import location_file


def storage_error_message(error) -> tuple[str, str]:
    translate = QCoreApplication.translate
    if str(error) == "speech_storage_location_unavailable":
        return (
            translate("StartupError", "所选语音资源位置不可用。"),
            translate("StartupError", "请连接或恢复所选磁盘后重新打开 Shinar；也可以检查下面的存储位置配置。"),
        )
    return (
        translate("StartupError", "语音资源的存储位置配置无法读取。"),
        translate("StartupError", "请检查下面的配置文件，修复后重新打开 Shinar。"),
    )


def create_storage_error_engine(error, *, config_path=None, engine_factory=None):
    factory = engine_factory or QQmlApplicationEngine
    engine = factory()
    message, advice = storage_error_message(error)
    engine.setInitialProperties({
        "errorMessage": message, "recoveryAdvice": advice,
        "configurationPath": str(location_file(config_path)),
    })
    qml = files("shinar.desktop").joinpath("qml/StartupError.qml")
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        raise RuntimeError("Shinar 启动错误窗口加载失败。")
    return engine


def show_storage_startup_error(error, *, app=None, config_path=None, engine_factory=None) -> int:
    application = app or QGuiApplication.instance() or QGuiApplication(["shinar-desktop"])
    from shinar.desktop.shell.identity import configure_application_identity

    configure_application_identity(application)
    engine = create_storage_error_engine(error, config_path=config_path, engine_factory=engine_factory)
    application.aboutToQuit.connect(lambda: _keep_error_window(engine))
    application.exec()
    return 1


def _keep_error_window(_engine) -> None:
    return None
