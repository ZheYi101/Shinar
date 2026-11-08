"""Visible QML provisioning in an isolated cache; real downloads, zero paid AI calls."""
# ruff: noqa: E402

import argparse
import json
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from PySide6.QtCore import (
    QObject,
    QMetaObject,
    QSettings,
    QUrl,
    Qt,
    qInstallMessageHandler,
    QCoreApplication,
    QEvent,
)
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer

from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.speech_library import SpeechLibraryViewModel
from shinar.desktop.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider
from validate_local_speech_desktop import click, find_item


def main(args):
    root = args.root or Path("build/speech-settings-closure") / ("qml-" + uuid4().hex)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    warnings = []
    qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    app = QGuiApplication([])
    assert app.platformName() != "offscreen", "Visible validation requires a native Qt platform"
    if os.name == "nt":
        for name in ("msyh.ttc", "YuGothR.ttc", "seguiemj.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
    library = SpeechLibraryViewModel(root / "cache")
    prefs = DesktopPreferences(QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat))
    vm = LearningViewModel(
        LearningWorkbench(
            MockLearningLLMProvider(), event_store=SQLiteStore(root / "learning.sqlite3")
        ),
        "Mock · speech settings validation",
        preferences=prefs,
    )
    engine = create_engine(
        vm,
        speech_library=library,
        window_settings=QSettings(str(root / "window.ini"), QSettings.Format.IniFormat),
    )
    window, workspace = engine.rootObjects()[0], engine.workspace
    window.setTitle("Shinar · 本地语音设置独立验证")
    window.setWidth(1180)
    window.setHeight(900)
    window.show()
    assert QTest.qWaitForWindowExposed(window)
    window.grabWindow()
    report = {
        "root": str(root),
        "real_asset_preparation_requested": bool(args.runtimes or args.continuous),
        "paid_model_calls": 0,
        "human_device_acceptance": False,
        "qt_platform": app.platformName(),
        "visible_window": True,
        "steps": [],
    }

    def wait(predicate, timeout=1800):
        deadline, last = monotonic() + timeout, None
        while not predicate():
            if not window.isVisible():
                raise RuntimeError("validation_window_closed")
            if monotonic() > deadline:
                raise RuntimeError("Validation step timed out")
            if library.status != last:
                last = library.status
                print(json.dumps({"stage": last}), flush=True)
            # qWait can retain the GIL and starve Python archive/download jobs.
            # Pump the owned UI, then release the GIL while its worker progresses.
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            sleep(0.02)

    def done(label, start):
        wait(lambda: not library.busy)
        report["steps"].append(
            {"name": label, "elapsed_ms": (monotonic() - start) * 1000, "status": library.status}
        )

    def models_page():
        workspace.setCategory("local")
        workspace.navigate("settings")
        QTest.qWait(150)
        wait(lambda: not library.busy)

    try:
        models_page()
        if args.runtimes:
            click(window, "openSpeechCompute")
            wait(lambda: not library.busy)
            for name in args.runtimes.split(","):
                start = monotonic()
                click(window, "prepareRuntime-" + name, "speechComputePage")
                done("prepare-runtime-" + name, start)
                assert library.runtimes[name]["prepared"], library.status
            click(window, "speechSettingsBack")
        if args.device:
            click(window, "openSpeechCompute")
            wait(lambda: not library.busy)
            choice = find_item(window, "compute-tts_device")
            choice.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Home)
            app.processEvents()
            wait(lambda: not library.busy)
            for _ in range({"auto": 0, "cpu": 1, "cuda": 2}[args.device]):
                choice.forceActiveFocus()
                QTest.keyClick(window, Qt.Key.Key_Down)
                app.processEvents()
                wait(lambda: not library.busy)
            QTest.qWait(100)
            wait(lambda: not library.busy)
            assert library.compute["tts_device"] == args.device
            click(window, "speechSettingsBack")
        for package_id in args.packages.split(",") if args.packages else []:
            language = args.language or (
                "ja" if package_id in {"voicevox-japanese", "reazonspeech-k2-v2-int8"} else "en"
            )
            choice = find_item(window, "speechLanguage")
            choice.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Home)
            QTest.qWait(120)
            wait(lambda: not library.busy)
            for _ in range(["ja", "en", "zh"].index(language)):
                choice.forceActiveFocus()
                QTest.keyClick(window, Qt.Key.Key_Down)
                QTest.qWait(120)
                wait(lambda: not library.busy)
            row = next(r for r in library.models if r["id"] == package_id)
            click(window, "speechTab" + row["task"])
            if package_id == "voicevox-japanese" or args.voice_index:
                click(window, "speechDetails-" + package_id, "speechModelsPage")
            if package_id == "voicevox-japanese":
                if not next(r for r in library.models if r["id"] == package_id)["termsAccepted"]:
                    click(window, "speechTerms-" + package_id, "speechModelsPage")
                    wait(lambda: not library.busy)
            if args.voice_index:
                choice = find_item(window, "speechVoice-" + package_id)
                choice.forceActiveFocus()
                QTest.keyClick(window, Qt.Key.Key_Home)
                QTest.qWait(100)
                wait(lambda: not library.busy)
                for _ in range(args.voice_index):
                    choice.forceActiveFocus()
                    QTest.keyClick(window, Qt.Key.Key_Down)
                    QTest.qWait(100)
                    wait(lambda: not library.busy)
            start = monotonic()
            row = next(r for r in library.models if r["id"] == package_id)
            if not row["installed"] or not row["runtimeReady"]:
                report["real_asset_preparation_requested"] = True
                click(window, "speechInstall-" + package_id, "speechModelsPage")
                done("prepare-package-" + package_id, start)
            row = next(r for r in library.models if r["id"] == package_id)
            assert row["installed"] and row["runtimeReady"], library.status
            if args.skip_benchmark:
                continue
            if not row["benchmarkable"]:
                click(window, "speechRefresh")
                wait(lambda: not library.busy)
                row = next(r for r in library.models if r["id"] == package_id)
                assert row["benchmarkable"], row["reason"]
            start = monotonic()
            if row["task"] == "STT" and args.wav:
                assert args.wav.is_file(), "The optional custom sample must exist"
                details = find_item(window, "speechModel-" + package_id)
                if not details.property("expanded"):
                    click(window, "speechDetails-" + package_id, "speechModelsPage")
                click(window, "speechCustomBenchmark-" + package_id, "speechModelsPage")
                dialog = window.findChild(QObject, "speechBenchmarkFile")
                assert dialog is not None
                assert dialog.setProperty(
                    "selectedFile", QUrl.fromLocalFile(str(args.wav.resolve()))
                )
                assert (
                    Path(dialog.property("selectedFile").toLocalFile()).resolve()
                    == args.wav.resolve()
                )
                # Exercise the QML acceptance handler with an explicit permitted fixture.
                # Native picker interaction is a separate manual check.
                assert QMetaObject.invokeMethod(dialog, "accepted")
                assert QMetaObject.invokeMethod(dialog, "reject")
                QTest.qWait(100)
                report["file_selection_method"] = (
                    "Qt FileDialog selectedFile and accepted signal; native picker not tested"
                )
            else:
                click(window, "speechBenchmark-" + package_id, "speechModelsPage")
                report["file_selection_method"] = "bundled language demo; no file picker"
            done("benchmark-" + package_id, start)
            assert next(r for r in library.models if r["id"] == package_id)["measured"], (
                library.status
            )
            if not next(r for r in library.models if r["id"] == package_id)["selected"]:
                click(window, "speechSelect-" + package_id, "speechModelsPage")
            assert next(r for r in library.models if r["id"] == package_id)["selected"]
            if args.preview and row["task"] == "TTS":
                start = monotonic()
                click(window, "speechPreview-" + package_id, "speechModelsPage")
                wait(
                    lambda: (
                        library._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                        or library._player.error() != QMediaPlayer.Error.NoError
                    ),
                    timeout=15,
                )
                assert library._player.error() == QMediaPlayer.Error.NoError, library.status
                started_ms = (monotonic() - start) * 1000
                wait(
                    lambda: (
                        library._player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia
                        or library._player.error() != QMediaPlayer.Error.NoError
                    ),
                    timeout=60,
                )
                assert library._player.error() == QMediaPlayer.Error.NoError, library.status
                report["steps"].append(
                    {
                        "name": "preview-" + package_id,
                        "player_started_ms": started_ms,
                        "elapsed_ms": (monotonic() - start) * 1000,
                        "human_listening": False,
                    }
                )
                click(window, "speechStopPreview-" + package_id, "speechModelsPage")
        if args.continuous:
            workspace.setCategory("audio")
            QTest.qWait(150)
            call = vm.voice.call
            start = monotonic()
            click(window, "prepareContinuousVoice", "settingsOverview")
            wait(lambda: call.connectionState != "preparing")
            report["steps"].append(
                {
                    "name": "prepare-continuous-components",
                    "elapsed_ms": (monotonic() - start) * 1000,
                    "status": call.noticeText or call.errorText,
                }
            )
            assert call.environmentReady and call.assetsReady, call.errorText
            assert not vm._audio.is_recording if hasattr(vm._audio, "is_recording") else True
            models_page()
        paths = []
        for width in (360, 600, 800, 1180, 1440):
            window.setWidth(width)
            from PySide6.QtCore import QPointF

            def resized():
                window.grabWindow()
                control = find_item(window, "windowCloseButton")
                return control.mapToScene(QPointF()).x() + control.width() <= window.width() + 1

            wait(resized, timeout=10)
            if args.packages:
                target = find_item(window, "speechModel-" + args.packages.split(",")[-1])
                flick = find_item(window, "speechModelsPage").property("contentItem")
                y = target.mapToItem(flick, QPointF()).y() + flick.property("contentY")
                flick.setProperty(
                    "contentY",
                    max(0, min(y - 12, flick.property("contentHeight") - flick.height())),
                )
                app.processEvents()
                sleep(0.1)
                app.processEvents()
            path = root / ("models-" + str(width) + ".png")
            assert window.grabWindow().save(str(path))
            paths.append(str(path))
        report.update(passed=True, screenshots=paths, benchmark_skipped=args.skip_benchmark)
    finally:
        window.grabWindow().save(str(root / "last-state.png"))
        report["last_setup_error"] = library.lastSetupError
        report["final_status"] = library.status
        report["qml_errors"] = [
            w
            for w in warnings
            if any(
                s in w.lower()
                for s in ("typeerror", "referenceerror", "binding loop", "cannot assign")
            )
        ]
        contents = json.dumps(report, ensure_ascii=False, indent=2)
        (root / "report.json").write_text(contents, encoding="utf-8")
        (root / ("attempt-" + uuid4().hex + ".json")).write_text(contents, encoding="utf-8")
        print(
            json.dumps(
                {
                    "report": str(root / "report.json"),
                    "passed": report.get("passed", False),
                    "qml_errors": len(report["qml_errors"]),
                }
            ),
            flush=True,
        )
        library.close()
        vm.close()
        window.close()
        engine.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--runtimes", default="")
    parser.add_argument("--packages", default="voicevox-japanese")
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Provisioning only; never claims synthesis or selection passed",
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"))
    parser.add_argument("--language", choices=("ja", "en", "zh"))
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--voice-index", type=int, default=0)
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Play a real local sample on the selected output; not human listening acceptance",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Prepare RTC/APM, VAD and SFU through audio settings; never opens the microphone",
    )
    main(parser.parse_args())
