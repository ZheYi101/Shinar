"""Window-close policy and system tray, without owning learning or worker state."""

from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.shell.window import DesktopWindowController


class DesktopLifecycleController(QObject):
    changed = Signal()

    def __init__(
        self,
        preferences: DesktopPreferences,
        window_controller: DesktopWindowController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._preferences = preferences
        self._controller = window_controller
        self._application = QGuiApplication.instance()
        self._window: QQuickWindow | None = None
        self._prompt_visible = False
        self._quitting = False
        self._quit_handler = None
        self._tray: QSystemTrayIcon | None = None
        self._menu: QMenu | None = None
        # QMenu needs QApplication. Headless QGuiApplication probes retain
        # ordinary close-to-exit behavior and never create widget objects.
        if isinstance(self._application, QApplication):
            self._menu = QMenu()
            self._menu.addAction(self.tr("打开 Shinar"), self.showWindow)
            self._menu.addSeparator()
            self._menu.addAction(self.tr("退出 Shinar"), self.quit)
            self.destroyed.connect(self._menu.deleteLater)
            self._tray = QSystemTrayIcon(self._application.windowIcon(), self)
            self._tray.setToolTip("Shinar")
            self._tray.setContextMenu(self._menu)
            self._tray.activated.connect(self._activated)
            self._tray.show()
        self._application.aboutToQuit.connect(self.close)

    def attach(self, window: QQuickWindow) -> None:
        self._window = window
        self._controller.set_close_handler(self.handle_close)

    @Property(bool, notify=changed)
    def backgroundAvailable(self) -> bool:
        return self._tray is not None and QSystemTrayIcon.isSystemTrayAvailable()

    @Property(bool, notify=changed)
    def closePromptVisible(self) -> bool:
        return self._prompt_visible

    def handle_close(self) -> bool:
        """Return True only when the native close has been handled here."""
        if self._application.isSavingSession():
            return False
        if self._quitting:
            return self._quit_handler is not None
        if not self.backgroundAvailable:
            if self._quit_handler is not None:
                self.quit()
                return True
            return False
        behavior = self._preferences.closeBehavior
        if behavior == "quit":
            if self._quit_handler is not None:
                self.quit()
                return True
            return False
        if behavior == "background":
            self._run_in_background()
        else:
            self._prompt_visible = True
            self.changed.emit()
        return True

    @Slot(str, bool)
    def chooseCloseBehavior(self, behavior: str, remember: bool) -> None:
        if not self._prompt_visible or behavior not in {"background", "quit"}:
            return
        if remember:
            self._preferences.setValue("closeBehavior", behavior)
        self.cancelClose()
        if behavior == "background" and self.backgroundAvailable:
            self._run_in_background()
        else:
            self.quit()

    @Slot()
    def cancelClose(self) -> None:
        self._prompt_visible = False
        self.changed.emit()

    def _run_in_background(self) -> None:
        if self._window is not None:
            self._window.hide()

    @Slot()
    def showWindow(self) -> None:
        if self._quitting or self._window is None:
            return
        if self._controller.maximized:
            self._window.showMaximized()
        else:
            self._window.showNormal()
        self._window.raise_()
        self._window.requestActivate()

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.showWindow()

    @Slot()
    def quit(self) -> None:
        self._quitting = True
        self.cancelClose()
        self._controller.save()
        if self._quit_handler is not None:
            self.showWindowForShutdown()
            self._quit_handler()
        else:
            self._application.quit()

    def set_quit_handler(self, handler) -> None:
        self._quit_handler = handler

    def showWindowForShutdown(self) -> None:
        if self._window is not None:
            self._window.show()
            self._window.raise_()

    @Slot()
    def close(self) -> None:
        """Remove native tray resources during explicit quit or engine teardown."""
        self._quitting = True
        self._quit_handler = None
        if self._window is not None:
            self._window.hide()
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
        if self._menu is not None:
            self._menu.deleteLater()
            self._menu = None
