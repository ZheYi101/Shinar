"""Isolated QML model-library probe; no learning data, cloud credentials or live mic."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import monotonic, sleep

from PySide6.QtCore import QObject, QPointF, QSettings, Qt, QCoreApplication, QEvent
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


def wait_until(predicate, timeout=180):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(25)
    if not predicate():
        raise RuntimeError("界面任务超时。")


def find_item(window, name):
    matches = []
    pending = [window.contentItem()]
    while pending:
        item = pending.pop()
        if item.objectName() == name:
            matches.append(item)
        pending.extend(item.childItems())
    if matches:
        return next((item for item in matches if item.isVisible()), matches[0])
    raise RuntimeError("未找到控件：" + name)


def click(window, name, scroll_name=None):
    app = QGuiApplication.instance()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    window.contentItem().ensurePolished()
    window.grabWindow()
    if scroll_name:
        scroll = find_item(window, scroll_name)
        flick = scroll.property("contentItem")
        for _ in range(3):
            item = find_item(window, name)
            y = item.mapToItem(flick, QPointF()).y() + flick.property("contentY")
            flick.setProperty(
                "contentY", max(0, min(y - 12, flick.property("contentHeight") - flick.height()))
            )
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            sleep(0.03)
            window.grabWindow()
    app.processEvents()
    window.contentItem().ensurePolished()
    window.grabWindow()
    item = find_item(window, name)
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    assert item.isVisible() and item.isEnabled() and 0 <= point.y() < window.height(), {
        "control": name, "visible": item.isVisible(), "enabled": item.isEnabled(),
        "x": point.x(), "y": point.y(), "window_height": window.height(),
    }
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(100)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("build/local-speech-evaluation"))
    parser.add_argument("--benchmark", help="Optional installed TTS id; runs real local inference")
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = root / "desktop"
    evidence.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(["local-speech-validation"])
    if os.name == "nt":
        for font in ("msyh.ttc", "msyhbd.ttc", "YuGothR.ttc"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
    library = SpeechLibraryViewModel(root / "cache")
    prefs = DesktopPreferences(QSettings(str(evidence / "prefs.ini"), QSettings.Format.IniFormat))
    vm = LearningViewModel(
        LearningWorkbench(
            MockLearningLLMProvider(), event_store=SQLiteStore(evidence / "app.sqlite3")
        ),
        "Mock 离线 UI 验证",
        preferences=prefs,
    )
    engine = create_engine(
        vm,
        window_settings=QSettings(str(evidence / "window.ini"), QSettings.Format.IniFormat),
        speech_library=library,
    )
    window = engine.rootObjects()[0]
    window.setWidth(800)
    window.setHeight(900)
    try:
        scaffold = next(
            obj
            for obj in window.findChildren(QObject)
            if obj.metaObject().indexOfProperty("currentPage") >= 0
        )
        scaffold.setProperty("currentPage", 3)
        QTest.qWait(200)
        button = find_item(window, "openLocalSpeechLibrary")
        parent = button.parentItem()
        while parent and parent.metaObject().indexOfProperty("contentY") < 0:
            parent = parent.parentItem()
        parent.setProperty("contentY", max(0, parent.property("contentHeight") - parent.height()))
        QTest.qWait(150)
        click(window, "openLocalSpeechLibrary")
        QTest.qWait(350)
        wait_until(lambda: not library.busy)
        # Exercise keyboard language selection, rather than setting the filter directly.
        language = find_item(window, "speechLanguage")
        language.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Down)
        QTest.qWait(150)
        wait_until(lambda: not library.busy)
        assert library.language == "en"
        if args.benchmark:
            click(window, "speechBenchmark-" + args.benchmark, "speechModelsPage")
            wait_until(lambda: not library.busy)
            assert "完成" in library.status, library.status
            click(window, "speechSelect-" + args.benchmark, "speechModelsPage")
        paths = []
        for theme in ("light", "dark"):
            prefs.setValue("themeMode", theme)
            for width in (360, 800, 1440):
                window.setWidth(width)
                flick = find_item(window, "speechModelsPage").property("contentItem")
                flick.setProperty("contentY", 0)
                QTest.qWait(200)
                path = evidence / f"model-library-{theme}-{width}.png"
                assert window.grabWindow().save(str(path))
                paths.append(str(path))
        click(window, "speechSettingsBack")
        click(window, "openSpeechCompute", "settingsOverview")
        wait_until(lambda: not library.busy)
        for theme in ("light", "dark"):
            prefs.setValue("themeMode", theme)
            for width in (360, 800, 1440):
                window.setWidth(width)
                flick = find_item(window, "speechComputePage").property("contentItem")
                flick.setProperty("contentY", 0)
                QTest.qWait(200)
                path = evidence / f"speech-compute-{theme}-{width}.png"
                assert window.grabWindow().save(str(path))
                paths.append(str(path))
        report = {
            "language": library.language,
            "hardware": library.hardwareSummary,
            "models": library.models,
            "screenshots": paths,
            "real_local_tts": args.benchmark,
            "live_microphone_or_voice_chain": False,
        }
        report_path = evidence / (
            "real-tts-" + args.benchmark + ".json" if args.benchmark else "report.json"
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"report": str(report_path), "screenshots": paths}, ensure_ascii=False))
    finally:
        library.close()
        vm.close()
        window.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
