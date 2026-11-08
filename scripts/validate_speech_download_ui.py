"""Capture compact STT/TTS settings with isolated, clearly synthetic transfers."""
# ruff: noqa: E402

import argparse
import json
import os
from pathlib import Path
import sys
from threading import Event
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["RUN_REAL_AI_TESTS"] = "0"
    os.environ["QT_QPA_PLATFORM"] = "windows" if args.visible else "offscreen"

    import pytest
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QWheelEvent
    from PySide6.QtTest import QTest
    from shinar.local_speech.catalog import load_catalog
    from shinar.local_speech.downloads import DownloadCancelled, TransferEvent
    from test_local_speech_desktop import library_desktop
    from test_desktop_workflow import click, item

    patch = pytest.MonkeyPatch()
    fixture_root = args.output / "isolated"
    fixture_root.mkdir(exist_ok=True)
    fixture = library_desktop.__wrapped__(fixture_root, patch)
    app, library, vm, window, engine, _ = next(fixture)
    stop = Event()
    captures, wheels = [], []

    def wait(predicate, timeout=10):
        deadline = monotonic() + timeout
        while not predicate() and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert predicate()

    def transfer(component):
        def run(cancel, stage, progress):
            stage("speech_setup_model")
            count = 4 * 1024**2
            while not stop.is_set():
                if cancel.wait(0.06):
                    raise DownloadCancelled()
                count = min(count + 8192, 28 * 1024**2)
                progress(TransferEvent(component, "downloading", count, 32 * 1024**2))

        return run

    try:
        window.setTitle("Shinar · 下载界面验收 · 合成任务与独立测试库")
        library.catalog = load_catalog()
        library.setFilter("en", "conversation")
        wait(lambda: not library.busy)
        stt = next(r for r in library.models if r["task"] == "STT" and r["downloadBytes"])
        tts = next(
            r
            for r in library.models
            if r["task"] == "TTS" and r["downloadBytes"] and not r["excluded"]
        )
        library.downloadJobs.enqueue(
            stt["id"], stt["name"], "stt", "en", transfer("sensevoice-model.onnx")
        )
        library.downloadJobs.enqueue(
            tts["id"], tts["name"], "tts", "en", transfer("tts-model.onnx")
        )
        wait(lambda: all(r["component"] for r in library.downloadJobs.rows()))
        for width in (360, 600, 800, 1180, 1440):
            window.setWidth(width)
            window.setHeight(900)
            for task in ("STT", "TTS"):
                click(window, "speechTab" + task)
                for _ in range(15):
                    app.processEvents()
                    sleep(0.01)
                pane = item(window, "speechModelsPage")
                assert pane.height() >= 140
                for name in ("speechLanguage", "speechTabSTT", "speechTabTTS"):
                    control = item(window, name)
                    corner = control.mapToScene(QPointF(control.width(), control.height()))
                    assert 0 < corner.x() <= width + 1 and 0 < corner.y() <= window.height()
                for job in library.downloadJobs.rows():
                    control = item(window, "cancelDownload-" + job["jobId"])
                    assert control.isVisible() and control.isEnabled()
                path = args.output / f"{width}-{task.lower()}.png"
                assert window.grabWindow().save(str(path))
                captures.append({"width": width, "task": task, "image": str(path)})
                flick = pane.property("contentItem")
                if flick.property("contentHeight") > flick.height() + 8:
                    bar = item(window, "speechModelScrollBar")
                    corner = bar.mapToItem(pane, QPointF())
                    assert corner.x() >= pane.width() - 16 and bar.height() >= pane.height() - 2
                    before = flick.property("contentY")
                    point = pane.mapToScene(QPointF(pane.width() / 2, pane.height() / 2))
                    QTest.mouseMove(window, point.toPoint())
                    app.processEvents()
                    event = QWheelEvent(
                        point,
                        window.mapToGlobal(point.toPoint()),
                        QPoint(),
                        QPoint(0, -120),
                        Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase,
                        False,
                    )
                    event.setTimestamp(int(monotonic() * 1000))
                    QGuiApplication.sendEvent(window, event)
                    try:
                        wait(lambda: flick.property("contentY") > before)
                    except AssertionError:
                        print(
                            json.dumps(
                                {
                                    "wheel_failure": {
                                        "width": width,
                                        "task": task,
                                        "before": before,
                                        "after": flick.property("contentY"),
                                        "origin": flick.property("originY"),
                                        "content_height": flick.property("contentHeight"),
                                        "height": flick.height(),
                                        "event_accepted": event.isAccepted(),
                                        "interactive": flick.property("interactive"),
                                    }
                                }
                            )
                        )
                        raise
                    wheels.append({"width": width, "task": task, "moved": True})
        rows = library.downloadJobs.rows()
        library.downloadJobs.cancel(rows[0]["jobId"])
        wait(lambda: library.downloadJobs.rows()[0]["state"] == "cancelled")
        assert library.downloadJobs.rows()[1]["state"] == "running"
        report = dict(
            passed=True,
            visible=args.visible,
            qt_platform=app.platformName(),
            scale=os.getenv("QT_SCALE_FACTOR", "system"),
            synthetic_transfers=True,
            real_models=False,
            microphone_open=False,
            paid_calls=0,
            captures=captures,
            wheels=wheels,
            independent_cancel=True,
        )
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"passed": True, "captures": len(captures), "wheel_checks": len(wheels)}))
    finally:
        stop.set()
        try:
            next(fixture)
        except StopIteration:
            pass
        patch.undo()


if __name__ == "__main__":
    main()
