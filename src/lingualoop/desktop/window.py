"""Frameless desktop window actions and bounded, DPI-independent restoration."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Property, QEvent, QRect, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from shiboken6 import isValid


class DesktopWindowController(QObject):
    changed = Signal()

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self._settings = settings if settings is not None else QSettings("LinguaLoop", "Window")
        self._window = None
        self._normal_geometry = QRect()
        self._close_handler: Callable[[], bool] | None = None

    def set_close_handler(self, handler: Callable[[], bool]) -> None:
        """Let the desktop lifecycle consume a close request before Qt exits."""
        self._close_handler = handler

    def attach(self, window):
        self._window = window
        window.installEventFilter(self)
        window.visibilityChanged.connect(self.changed)
        window.destroyed.connect(self._window_destroyed)
        value = self._settings.value("normalGeometry")
        if isinstance(value, QRect) and value.isValid():
            screen = next((item for item in QGuiApplication.screens()
                           if item.availableGeometry().intersects(value)), window.screen())
            bounds = screen.availableGeometry()
            width = max(window.minimumWidth(), min(value.width(), bounds.width()))
            height = max(window.minimumHeight(), min(value.height(), bounds.height()))
            x = max(bounds.x(), min(value.x(), bounds.right() - width + 1))
            y = max(bounds.y(), min(value.y(), bounds.bottom() - height + 1))
            window.setGeometry(x, y, width, height)
        self._normal_geometry = window.geometry()
        if str(self._settings.value("maximized", "false")).lower() == "true":
            if window.isVisible():
                window.showMaximized()
            else:
                window.setWindowState(Qt.WindowState.WindowMaximized)

    @Property(bool, notify=changed)
    def maximized(self):
        return bool(self._window and isValid(self._window) and self._window.windowState() == Qt.WindowState.WindowMaximized)

    def _window_destroyed(self, *_):
        self._window = None

    @Slot()
    def minimize(self):
        if self._window:
            self._window.showMinimized()

    @Slot()
    def toggleMaximized(self):
        if self._window:
            self._window.showNormal() if self.maximized else self._window.showMaximized()

    @Slot()
    def restore(self):
        if self._window:
            self._window.showNormal()

    @Slot()
    def close(self):
        if self._window:
            self._window.close()

    @Slot(result=bool)
    def startMove(self):
        return bool(self._window and self._window.startSystemMove())

    @Slot(int, result=bool)
    def startResize(self, edges):
        if not self._window or self.maximized:
            return False
        valid = int(Qt.Edge.LeftEdge.value | Qt.Edge.RightEdge.value | Qt.Edge.TopEdge.value | Qt.Edge.BottomEdge.value)
        if not edges or edges & ~valid:
            return False
        return self._window.startSystemResize(Qt.Edge(edges))

    def save(self):
        if self._window is None:
            return
        if self._normal_geometry.isValid():
            self._settings.setValue("normalGeometry", self._normal_geometry)
        self._settings.setValue("maximized", self.maximized)
        self._settings.sync()

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
                if self._window.windowState() == Qt.WindowState.WindowNoState:
                    self._normal_geometry = self._window.geometry()
            elif event.type() == QEvent.Type.Close:
                self.save()
                if self._close_handler and self._close_handler():
                    event.ignore()
                    return True
        return super().eventFilter(watched, event)
