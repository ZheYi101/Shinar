"""Exercise middle-button autoscroll through real QML mouse and key events."""


import pytest


from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from shinar.local_speech.catalog import load_catalog
from tests.support.qt import click, item, until


@pytest.mark.parametrize("width", [360, 1180])

def test_model_middle_button_scroll_and_exit(library_desktop, width):
    _, library, _, window, _, _ = library_desktop
    library.catalog = load_catalog()
    library.setFilter("en", "conversation")
    until(lambda: not library.busy)
    window.setWidth(width)
    # Exercise an overflowing viewport even as the downloadable catalogue changes.
    window.setHeight(600)
    QTest.qWait(100)
    pane = item(window, "speechModelsPage")
    scroll = item(window, "speechModelAutoScroll")
    flick = pane.property("contentItem")
    assert flick.property("contentHeight") > flick.height() + 100
    center = pane.mapToScene(QPointF(pane.width() / 2, pane.height() / 2)).toPoint()
    # Extra model status rows can leave a compact viewport; keep the pointer
    # inside it so this tests scrolling rather than the intentional exit handler.
    travel = min(85, int(pane.height() / 2) - 12)
    assert travel > 12

    def middle():
        QTest.mouseClick(window, Qt.MouseButton.MiddleButton, pos=center)
        until(lambda: scroll.property("scrolling"))

    def assert_stopped():
        until(lambda: not scroll.property("scrolling"))
        position = flick.property("contentY")
        QTest.qWait(100)
        assert flick.property("contentY") == position

    middle()
    beginning = flick.property("contentY")
    QTest.mouseMove(window, center + QPoint(0, 5))
    QTest.qWait(100)
    assert flick.property("contentY") == beginning  # Dead zone prevents drift.
    QTest.mouseMove(window, center + QPoint(0, travel))
    until(lambda: flick.property("contentY") > beginning + 15)
    lower = flick.property("contentY")
    QTest.mouseMove(window, center - QPoint(0, travel))
    until(lambda: flick.property("contentY") < lower - 10)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert_stopped()

    middle()
    QTest.mouseMove(window, center + QPoint(0, travel))
    QTest.qWait(100)
    QTest.mouseClick(window, Qt.MouseButton.MiddleButton, pos=center)
    assert_stopped()

    # A held middle-button drag scrolls until release.
    QTest.mousePress(window, Qt.MouseButton.MiddleButton, pos=center)
    until(lambda: scroll.property("scrolling"))
    position = flick.property("contentY")
    QTest.mouseMove(window, center + QPoint(0, travel))
    until(lambda: flick.property("contentY") > position + 10)
    QTest.mouseRelease(window, Qt.MouseButton.MiddleButton, pos=center + QPoint(0, travel))
    assert_stopped()

    middle()
    click(window, "speechTabTTS")
    assert_stopped()

    # Normal left clicks still reach model actions after autoscroll exits.
    package = next(row for row in library.models if row["task"] == "TTS" and not row["excluded"])
    click(window, "speechDetails-" + package["id"], scroll="speechModelsPage")
    assert item(window, "speechModel-" + package["id"]).property("expanded")
