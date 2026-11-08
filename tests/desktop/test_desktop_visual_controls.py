"""Live geometry and keyboard regressions for the paper controls."""

import pytest

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from tests.support.qt import click, item, until
from tests.support.scenarios import workspace_of



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


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [360, 1180])
def test_combo_moves_one_highlight_without_trails_or_clipped_rows(desktop, theme, width):
    vm, window, *_ = desktop
    vm.preferences.setValue("themeMode", theme)
    window.setWidth(width)
    ws = workspace_of(window)
    ws.navigate("settings")
    ws.setCategory("learning")
    QTest.qWait(60)
    click(window, "preference-targetLanguage")
    combo = item(window, "preference-targetLanguage")
    popup = window.findChild(QObject, "preference-targetLanguage-popup")
    until(lambda: popup.property("visible"))
    view = popup.property("contentItem")
    rows = {
        row.property("index"): row
        for row in view.property("contentItem").childItems()
        if row.metaObject().indexOfProperty("highlighted") >= 0
    }
    assert len(rows) == 6

    def assert_single_highlight(index):
        assert combo.property("highlightedIndex") == index
        for row_index, row in rows.items():
            alpha = row.property("background").property("color").alphaF()
            assert alpha == (1 if row_index == index else 0), (row_index, index, alpha)

    for index in (1, 2, 4):
        row = rows[index]
        center = row.mapToScene(QPointF(row.width() / 2, row.height() / 2)).toPoint()
        QTest.mouseMove(window, center)
        QTest.qWait(10)
        assert_single_highlight(index)

    # A stationary pointer must not keep a second row lit during keyboard use.
    QTest.keyClick(window, Qt.Key.Key_Down)
    assert_single_highlight(5)
    for row in rows.values():
        end = row.mapToItem(view, QPointF(row.width(), row.height()))
        assert end.x() <= view.width() and end.y() <= view.height()
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert vm.preferences.targetLanguage == "spanish"
    assert not popup.property("visible")

    click(window, "preference-targetLanguage")
    assert combo.property("highlightedIndex") == 5
    QTest.keyClick(window, Qt.Key.Key_Up)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert vm.preferences.targetLanguage == "spanish"
    assert not popup.property("visible")
