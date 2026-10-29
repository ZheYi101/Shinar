"""Live geometry and keyboard regressions for the paper controls."""

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from test_desktop_workflow import desktop, qt_app, click, item, until, workspace_of  # noqa: F401


def test_theme_tiles_and_compact_controls_are_interactive(desktop):
    vm, window, *_ = desktop
    ws = workspace_of(window)
    ws.navigate("settings")
    ws.setCategory("appearance")
    for width in (360, 800, 1440):
        window.setWidth(width)
        QTest.qWait(60)
        for theme in ("dark", "light"):
            click(window, "theme-" + theme)
            assert vm.preferences.themeMode == theme
            tile = item(window, "theme-" + theme)
            assert tile.property("selected")
            end = tile.mapToScene(QPointF(tile.width(), tile.height()))
            assert end.x() <= window.width() and end.y() <= window.height()
        click(window, "reducedMotionSwitch")
        assert vm.preferences.reducedMotion
        click(window, "reducedMotionSwitch")
        assert not vm.preferences.reducedMotion

    # Material's inherited insets used to shrink a 36px action's visible
    # background to 24px. Check the rendered surface, not just the hit target.
    button = item(window, "nav3")
    background = button.property("background")
    assert button.height() >= 36
    assert background.height() == button.height()
    assert background.width() == button.width()


def test_paper_combo_supports_keyboard_and_model_roles(desktop):
    vm, window, *_ = desktop
    ws = workspace_of(window)
    ws.navigate("settings")
    ws.setCategory("learning")
    QTest.qWait(60)
    combo = item(window, "preference-targetLanguage")
    combo.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Space)
    popup = window.findChild(QObject, "preference-targetLanguage-popup")
    assert popup is not None
    until(lambda: popup.property("visible"))
    QTest.keyClick(window, Qt.Key.Key_Down)
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert vm.preferences.targetLanguage == "english"
    assert not popup.property("visible")
    # Device controls use structured rows, unlike the simple preference arrays.
    ws.setCategory("audio")
    QTest.qWait(60)
    pending = [window.contentItem()]
    devices = []
    while pending:
        candidate = pending.pop()
        if candidate.isVisible() and candidate.property("textRole") == "name":
            devices.append(candidate.property("displayText"))
        pending.extend(candidate.childItems())
    assert "Test microphone" in devices and "Test speaker" in devices
