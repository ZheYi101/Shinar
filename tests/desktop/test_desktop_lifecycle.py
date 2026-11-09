"""Close policy, recoverable background operation and explicit application exit."""

import pytest

from PySide6.QtCore import QObject, QSettings, Qt
from PySide6.QtQml import QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QSystemTrayIcon

from shinar.desktop.shell.preferences import DesktopPreferences
from tests.support.qt import click, item, until
from tests.support.scenarios import load_and_start, workspace_of



class FakeTray(QObject):
    def hide(self):
        pass


@pytest.fixture
def lifecycle(desktop, monkeypatch):
    _, window, *_ = desktop
    controller = QQmlEngine.contextForObject(window).contextProperty("desktopLifecycle")
    controller._tray = FakeTray(controller)
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    controller.changed.emit()
    yield controller
    controller.close()


def test_close_preference_defaults_validates_and_persists(tmp_path):
    path = str(tmp_path / "preferences.ini")
    settings = QSettings(path, QSettings.Format.IniFormat)
    prefs = DesktopPreferences(settings)
    assert prefs.closeBehavior == "ask"
    prefs.setValue("closeBehavior", "background")
    prefs.setValue("closeBehavior", "invalid")
    assert (
        DesktopPreferences(QSettings(path, QSettings.Format.IniFormat)).closeBehavior
        == "background"
    )
    settings.setValue("closeBehavior", "corrupt")
    assert prefs.closeBehavior == "ask"


@pytest.mark.parametrize("width", [360, 1180])
def test_close_dialog_cancel_escape_and_unremembered_choice(desktop, lifecycle, width):
    vm, window, *_ = desktop
    window.setWidth(width)
    click(window, "windowCloseButton")
    assert window.isVisible() and lifecycle.closePromptVisible
    click(window, "cancelWindowCloseButton")
    assert window.isVisible() and not lifecycle.closePromptVisible
    QTest.qWait(200)
    QTest.keyClick(window, Qt.Key.Key_F4, Qt.KeyboardModifier.AltModifier)
    assert lifecycle.closePromptVisible
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not lifecycle.closePromptVisible and window.isVisible()
    QTest.qWait(200)
    click(window, "windowCloseButton")
    click(window, "closeToBackgroundButton")
    assert not window.isVisible() and not lifecycle.closePromptVisible
    assert vm.preferences.closeBehavior == "ask"
    lifecycle.showWindow()
    assert window.isVisible()


def test_background_preserves_draft_reply_and_maximized_window(desktop, lifecycle):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    thread_id = vm._workbench.session.id
    vm.sendMessage("I think she wanted to keep her promise.")
    vm.draft = "Keep this unsent thought."
    click(window, "windowMaximizeButton")
    click(window, "windowCloseButton")
    click(window, "rememberCloseChoice")
    click(window, "closeToBackgroundButton")
    assert not window.isVisible() and vm.preferences.closeBehavior == "background"
    until(lambda: not vm.busy)
    assert vm.messages[-1]["role"] == "assistant" and vm.messages[-1]["content"]
    lifecycle.showWindow()
    assert window.windowState() == Qt.WindowState.WindowMaximized
    assert vm._workbench.session.id == thread_id and vm.draft == "Keep this unsent thought."
    click(window, "windowCloseButton")
    assert not window.isVisible() and not lifecycle.closePromptVisible
    lifecycle.showWindow()


@pytest.mark.parametrize("available,behavior", [(False, "background"), (True, "quit")])
def test_direct_exit_and_tray_unavailable_never_strand_a_hidden_process(
    desktop, lifecycle, monkeypatch, available, behavior
):
    vm, window, *_ = desktop
    requested = []
    vm.preferences.setValue("closeBehavior", behavior)
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: available)
    monkeypatch.setattr(lifecycle._application, "quit", lambda: requested.append(True))
    assert not window.close()  # Native close is consumed while cleanup runs.
    until(lambda: bool(requested))
    assert not window.isVisible() and not lifecycle.closePromptVisible


def test_explicit_quit_overrides_background_and_remembered_dialog_choice(
    desktop, lifecycle, monkeypatch
):
    vm, window, *_ = desktop
    requested = []
    monkeypatch.setattr(lifecycle._application, "quit", lambda: requested.append(True))
    click(window, "windowCloseButton")
    click(window, "rememberCloseChoice")
    click(window, "quitApplicationButton")
    until(lambda: bool(requested))
    assert requested == [True] and vm.preferences.closeBehavior == "quit"
    assert not lifecycle.closePromptVisible
    assert not lifecycle.handle_close()


def test_close_behavior_setting_can_be_changed_with_keyboard(desktop, lifecycle):
    vm, window, *_ = desktop
    ws = workspace_of(window)
    ws.navigate("settings")
    ws.setCategory("appearance")
    QTest.qWait(60)
    combo = item(window, "preference-closeBehavior")
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Space)
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert vm.preferences.closeBehavior == "background"


def test_tray_activation_and_conversation_menu_override_background_choice(
    desktop, lifecycle, monkeypatch
):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    vm.preferences.setValue("closeBehavior", "background")
    click(window, "windowCloseButton")
    assert not window.isVisible()
    lifecycle._activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert window.isVisible()
    requested = []
    monkeypatch.setattr(lifecycle._application, "quit", lambda: requested.append(True))
    click(window, "conversationMenuButton")
    click(window, "exitApplicationMenuItem")
    until(lambda: bool(requested))
    assert requested == [True] and not lifecycle.closePromptVisible
    assert vm.preferences.closeBehavior == "background"
