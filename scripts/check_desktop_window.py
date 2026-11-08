"""Check the actual Win32 frame without ever showing a window or reading .env."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["SHINAR_KIRIGAMI_MODE"] = "off"

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


def main():
    app = QGuiApplication([])
    with TemporaryDirectory() as directory:
        root = Path(directory)
        vm = LearningViewModel(LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(root / "probe.sqlite3")),
            "Mock 窗口检查", preferences=DesktopPreferences(QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat)))
        engine = create_engine(vm, window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat), initial_visible=False)
        window = engine.rootObjects()[0]
        try:
            app.processEvents()
            assert not window.isVisible()
            assert window.flags() & Qt.WindowType.FramelessWindowHint
            report = {"platform": app.platformName(), "visible": window.isVisible(), "frameless": True}
            if os.name == "nt":
                from ctypes import wintypes
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                get_style = user32.GetWindowLongW
                get_style.argtypes = [wintypes.HWND, ctypes.c_int]
                get_style.restype = wintypes.LONG
                handle = int(window.winId())
                style = get_style(handle, -16) & 0xFFFFFFFF
                assert not style & 0x00C00000, f"Native WS_CAPTION is present: {style:#x}"
                report.update({"win32_style": hex(style), "native_caption": False,
                               "device_pixel_ratio": window.devicePixelRatio()})
            print(json.dumps(report, ensure_ascii=False))
        finally:
            engine.lifecycle.close()
            engine.workspace.close()
            engine.speech_library.close()
            vm.close()
            window.close()
            engine.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    main()
