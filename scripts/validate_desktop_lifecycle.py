"""Verify close-to-tray and real event-loop exit in an isolated Windows Mock app."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["RUN_REAL_AI_TESTS"] = "0"
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["SHINAR_KIRIGAMI_MODE"] = "off"

from PySide6.QtCore import QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest

from shinar.application import LearningWorkbench
from shinar.desktop.app import _load_qt, create_engine
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider
from validate_ui_workspace import SyntheticAudio, click, visible_item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/desktop-lifecycle"))
    parser.add_argument("--exit-via", choices=("tray", "dialog", "window"), default="tray")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    qt = _load_qt()
    app = qt["QApplication"]([])
    results, errors = [], []
    state = {"completed": False, "delivered_while_hidden": False}
    with TemporaryDirectory(prefix="shinar-lifecycle-") as directory:
        root = Path(directory)
        prefs = DesktopPreferences(QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat))
        vm = LearningViewModel(
            LearningWorkbench(
                MockLearningLLMProvider(), event_store=SQLiteStore(root / "library.db")
            ),
            "Mock",
            preferences=prefs,
            audio_controller=SyntheticAudio(),
        )
        engine = create_engine(
            vm, window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat)
        )
        window, lifecycle = engine.rootObjects()[0], engine.lifecycle
        app.aboutToQuit.connect(vm.close)
        pending = []

        def guard(action):
            def execute():
                try:
                    action()
                except BaseException as error:
                    errors.append(repr(error))
                    app.quit()

            return execute

        def capture(label):
            QTest.qWait(220)
            path = args.output / f"{args.exit_via}-{label}.png"
            assert window.grabWindow().save(str(path))
            results.append(dict(check=label, capture=path.name, passed=True))

        def tray_action(index):
            menu = lifecycle._tray.contextMenu()
            menu.popup(QCursor.pos())
            QTest.qWait(80)
            point = menu.actionGeometry(menu.actions()[index]).center()
            QTest.mouseClick(menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)

        def delivered(job_id, value, error):
            if job_id == "lifecycle-check":
                assert value == "completed" and not error
                state["delivered_while_hidden"] = not window.isVisible()

        vm._worker.jobCompleted.connect(delivered)

        async def background_work():
            await asyncio.sleep(0.4)
            return "completed"

        def start():
            assert lifecycle.backgroundAvailable, "A real Windows system tray is required"
            assert lifecycle._tray.isVisible()
            window.setHeight(780)
            for theme in ("light", "dark"):
                prefs.setValue("themeMode", theme)
                for width in (1180, 360):
                    window.setWidth(width)
                    QTest.qWait(100)
                    click(window, "windowCloseButton")
                    assert lifecycle.closePromptVisible and window.isVisible()
                    for name in (
                        "closeToBackgroundButton",
                        "quitApplicationButton",
                        "rememberCloseChoice",
                    ):
                        target = visible_item(window, name)
                        end = target.mapToScene(QPointF(target.width(), target.height()))
                        assert 0 < end.x() <= window.width() and 0 < end.y() <= window.height()
                    capture(f"{theme}-{width}")
                    click(window, "cancelWindowCloseButton")
                    assert not lifecycle.closePromptVisible and window.isVisible()
            vm.draft = "A draft that must survive hiding."
            click(window, "windowCloseButton")
            click(window, "rememberCloseChoice")
            pending.append(vm._worker.submit_job("lifecycle-check", background_work))
            click(window, "closeToBackgroundButton")
            assert not window.isVisible() and prefs.closeBehavior == "background"
            QTimer.singleShot(700, guard(resume))

        def resume():
            assert not window.isVisible()
            assert pending[0].done() and state["delivered_while_hidden"]
            tray_action(0)
            assert window.isVisible() and vm.draft == "A draft that must survive hiding."
            restored = DesktopPreferences(
                QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat)
            )
            assert restored.closeBehavior == "background"
            results.append(dict(check="background_worker_tray_restore_persistence", passed=True))
            if args.exit_via == "dialog":
                prefs.setValue("closeBehavior", "ask")
                click(window, "windowCloseButton")
                click(window, "rememberCloseChoice")
                state["completed"] = True
                click(window, "quitApplicationButton")
                assert prefs.closeBehavior == "quit"
            elif args.exit_via == "window":
                prefs.setValue("closeBehavior", "quit")
                state["completed"] = True
                click(window, "windowCloseButton")
            else:
                click(window, "windowCloseButton")
                assert not window.isVisible() and not lifecycle.closePromptVisible
                state["completed"] = True
                tray_action(2)

        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: (errors.append("event_loop_timeout"), app.quit()))
        watchdog.start(20000)
        QTimer.singleShot(100, guard(start))
        app.exec()
        watchdog.stop()
        assert state["completed"] and not errors, (state, errors)
        assert vm._worker._thread is None or not vm._worker._thread.is_alive()
        assert engine.ai_services._closed and lifecycle._tray is None
        results.append(dict(check=f"{args.exit_via}_exit_and_cleanup", passed=True))
        window.close()
        engine.deleteLater()
        app.processEvents()
    report = dict(platform=app.platformName(), provider="mock", checks=results)
    (args.output / f"{args.exit_via}-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
