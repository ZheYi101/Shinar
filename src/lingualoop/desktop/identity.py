"""Application identity shared by source, wheel and Windows distribution entry points."""

from __future__ import annotations

import ctypes
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
import os
from typing import Any

WINDOWS_APP_ID = "LinguaLoop.Desktop"


def set_windows_app_id() -> None:
    """Match the installer shortcut identity before Qt creates a native window."""
    if os.name == "nt":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)


def configure_application_identity(app: Any) -> None:
    from PySide6.QtGui import QIcon

    app.setApplicationName("LinguaLoop")
    app.setApplicationDisplayName("LinguaLoop")
    app.setOrganizationName("LinguaLoop")
    try:
        app.setApplicationVersion(version("lingualoop"))
    except PackageNotFoundError:
        app.setApplicationVersion("0.1.3")
    icon = QIcon(str(files("lingualoop.desktop").joinpath("assets/app-icon.ico")))
    if icon.isNull():
        raise RuntimeError("LinguaLoop 应用图标缺失，请重新安装应用。")
    app.setWindowIcon(icon)
