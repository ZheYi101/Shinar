"""Qt interaction helpers. Callers choose the platform before creating an app."""

import os
from pathlib import Path
from time import monotonic, sleep
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest


def ensure_app():
    app = QGuiApplication.instance() or QGuiApplication(["shinar-interaction-test"])
    if os.name == "nt":
        for name in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name)
            )
    return app


def until(predicate, timeout=5000):
    deadline = monotonic() + timeout / 1000
    while not predicate() and monotonic() < deadline:
        QGuiApplication.instance().processEvents()
        sleep(0.01)
    assert predicate()


def item(window, name):
    result = window.findChild(QQuickItem, name)
    if result is None:
        pending = [window.contentItem()]
        while pending:
            candidate = pending.pop()
            if candidate.objectName() == name:
                result = candidate
                break
            pending.extend(candidate.childItems())
    assert result is not None, name
    return result


def click(window, name, *, scroll=None):
    target = item(window, name)
    if scroll:
        view = item(window, scroll)
        flick = view.property("contentItem")
        # Scroll against the live, polished geometry. A first data notification
        # can change card heights after the first requested content position.
        for _ in range(5):
            target = item(window, name)
            y = target.mapToItem(flick, QPointF()).y() + flick.property("contentY")
            flick.setProperty(
                "contentY", max(0, min(y - 16, flick.property("contentHeight") - flick.height()))
            )
            QTest.qWait(60)
            target = item(window, name)
            viewport_point = target.mapToItem(
                view, QPointF(target.width() / 2, target.height() / 2)
            )
            if 0 <= viewport_point.x() < view.width() and 0 <= viewport_point.y() < view.height():
                break
        assert 0 <= viewport_point.x() < view.width() and 0 <= viewport_point.y() < view.height(), (
            name,
            viewport_point,
        )
    # Qt Quick polishes Flow/Layout geometry asynchronously, including when a
    # record action changes the visible controls. Wait for a stable hit point.
    previous_geometry = None
    stable = 0
    for _ in range(12):
        target = item(window, name)
        center = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
        geometry = (center.x(), center.y(), target.width(), target.height())
        stable = stable + 1 if geometry == previous_geometry else 0
        if stable >= 2:
            break
        previous_geometry = geometry
        QTest.qWait(20)
    assert stable >= 2, (name, "Control geometry did not settle")
    assert target.isVisible(), name
    assert target.isEnabled(), name
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    assert 0 <= point.x() < window.width() and 0 <= point.y() < window.height(), (name, point)
    QTest.mouseMove(window, point)
    QTest.qWait(20)
    # Hover processing may deliver a pending layout polish; press the current
    # center rather than a coordinate measured before that event processing.
    target = item(window, name)
    point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(20)
    try:
        assert target.property("down"), (
            name,
            "The actual control did not receive the mouse press",
            point,
            target.mapToScene(QPointF(target.width() / 2, target.height() / 2)),
        )
    finally:
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)
