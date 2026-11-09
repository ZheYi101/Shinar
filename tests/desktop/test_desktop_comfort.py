"""Conversation reading, keyboard entry and navigation remain usable across widths."""

import pytest

from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from tests.support.qt import click, item, until
from tests.support.scenarios import load_and_start, workspace_of



def test_conversation_wraps_user_messages_and_allows_copy(desktop):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    text = "I think she wanted to explain herself. " * 6
    vm.draft = text
    click(window, "sendMessageButton")
    until(lambda: not vm.busy)
    user = next(message for message in vm.messages if message["role"] == "user")
    body = item(window, "messageBody-" + user["id"])
    for width in (360, 800, 1180):
        window.setWidth(width)
        QTest.qWait(80)
        assert item(window, "mockDialogueNotice").isVisible()
        assert body.width() > 100, (
            body.width(),
            body.parentItem().width(),
            body.parentItem().parentItem().width(),
        )
        assert body.property("contentHeight") > 20
        end = body.mapToScene(QPointF(body.width(), body.height()))
        assert end.x() <= window.width()
    button = item(window, "copyMessage-" + user["id"])
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseMove(window, point)
    QTest.qWait(140)
    click(window, "copyMessage-" + user["id"])
    assert QGuiApplication.clipboard().text() == user["content"]


def test_enter_sends_and_shift_enter_keeps_multiline_draft(desktop):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    editor = item(window, "messageInput")
    editor.setProperty("text", "First line")
    editor.forceActiveFocus()
    editor.setProperty("cursorPosition", len("First line"))
    QTest.keyClick(window, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert vm.draft == "First line\n"
    editor.setProperty("text", "First line\nSecond line")
    QTest.keyClick(window, Qt.Key.Key_Return)
    until(lambda: not vm.busy and len(vm.messages) == 3)
    assert vm.messages[1]["content"] == "First line\nSecond line"
    assert not vm.draft


def test_review_is_in_library_and_sidebar_toggle_preserves_draft(desktop):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    vm.draft = "Keep this thought."
    workspace = workspace_of(window)
    click(window, "sidebarToggle")
    until(lambda: workspace.collapsed)
    assert item(window, "sidebarToggle").property("label") == "展开侧栏"
    click(window, "sidebarToggle")
    until(lambda: not workspace.collapsed)
    assert vm.draft == "Keep this thought."
    click(window, "nav0")
    click(window, "nav2")
    assert workspace.route == "queue"


def test_sidebar_button_has_hover_press_and_reduced_motion_feedback(desktop):
    vm, window, *_ = desktop
    button = item(window, "sidebarToggle")
    surface = button.property("background")
    QTest.mouseMove(window, QPointF(window.width() / 2, 300).toPoint())
    QTest.qWait(140)
    resting = surface.property("color")
    center = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseMove(window, center)
    QTest.qWait(140)
    assert surface.property("color") != resting
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.qWait(140)
    assert button.property("down") and surface.property("scale") < 1
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    vm.preferences.setValue("reducedMotion", True)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QGuiApplication.processEvents()
    assert surface.property("scale") == 0.92
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)


def _sidebar_icon_geometry(window, name):
    button = item(window, name)
    pending = [button.property("contentItem")]
    while pending:
        candidate = pending.pop()
        source = candidate.property("source")
        if isinstance(source, QUrl) and source.toString().endswith("/" + button.property("symbol") + ".svg"):
            center = candidate.mapToScene(QPointF(candidate.width() / 2, candidate.height() / 2))
            return center.x(), center.y(), candidate.width(), candidate.height()
        pending.extend(candidate.childItems())
    raise AssertionError(f"No rendered icon found for {name}")


@pytest.mark.parametrize("width", [800, 1180])
def test_sidebar_icons_and_brand_stay_aligned_during_collapse(desktop, width):
    vm, window, *_ = desktop
    window.setWidth(width)
    workspace = workspace_of(window)
    workspace.navigate("settings")
    names = ["nav0", "nav3"] + ["settings-" + key for key in (
        "appearance", "learning", "services", "audio", "local", "data"
    )]
    QTest.qWait(200)
    expected = {name: _sidebar_icon_geometry(window, name) for name in names}
    brand = item(window, "sidebarBrandIcon")
    brand_center = brand.mapToScene(QPointF(brand.width() / 2, brand.height() / 2))
    for collapsed in (True, False):
        workspace.toggleSidebar()
        assert workspace.collapsed is collapsed
        for delay in (0, 40, 80, 140):
            QTest.qWait(delay)
            for name in names:
                geometry = _sidebar_icon_geometry(window, name)
                assert geometry == pytest.approx(expected[name], abs=0.5), (name, collapsed, delay)
                assert geometry[0] == pytest.approx(brand_center.x(), abs=0.5)
                assert geometry[2:] == (24, 24)
            actual_brand = brand.mapToScene(QPointF(brand.width() / 2, brand.height() / 2))
            assert actual_brand == brand_center
