"""Visible or offscreen storage UI evidence using disposable synthetic resources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def capture(window, directory, name):
    from PySide6.QtTest import QTest

    QTest.qWait(450)
    path = directory / (name + ".png")
    assert window.grabWindow().save(str(path))
    return path.name


def run_probe(root, evidence):
    from PySide6.QtCore import QObject, QMetaObject
    from tests.support.qt import click, ensure_app, until
    from tests.support.speech_library import speech_library_scene

    app = ensure_app()
    screenshots = []
    with speech_library_scene(root, navigate=False) as (_, library, vm, window, engine, _):
        controller = engine.storage_management
        bounds = window.screen().availableGeometry()
        window.setWidth(min(1180, bounds.width() - 32))
        window.setHeight(min(900, bounds.height() - 32))
        window.setX(bounds.x() + 16)
        window.setY(bounds.y() + 16)
        window.requestActivate()
        payload = b"cache" * 1024**2
        blob = library.store.root / "downloads" / hashlib.sha256(payload).hexdigest()
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(payload)
        try:
            click(window, "openSpeechStorage")
            page = window.findChild(QObject, "speechStoragePage")
            until(lambda: page.property("visible") and not controller.busy and bool(controller.inventory))
            for theme, width in (("light", 1180), ("dark", 1180), ("light", 760)):
                vm.preferences.setValue("theme", theme)
                window.setWidth(min(width, bounds.width() - 32))
                screenshots.append(capture(window, evidence, f"{theme}-{width}"))
            click(window, "speechStorageHelp")
            screenshots.append(capture(window, evidence, "space-help"))
            # Existing help popup exposes its explicit close action through QML.
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            QTest.keyClick(window, Qt.Key.Key_Escape)
            click(window, "cleanSpeechCache")
            dialog = window.findChild(QObject, "speechCacheConfirmation")
            assert blob.exists() and dialog.property("visible")
            screenshots.append(capture(window, evidence, "cleanup-preview"))
            assert QMetaObject.invokeMethod(dialog, "accept")
            until(lambda: not controller.busy and not blob.exists(), timeout=15000)
            screenshots.append(capture(window, evidence, "cleanup-complete"))
            page.setProperty("awaitingPreview", True)
            controller.previewMigration(str(root / "new-speech"))
            until(lambda: not controller.busy and bool(controller.migration), timeout=15000)
            dialog = window.findChild(QObject, "speechStorageConfirmation")
            until(lambda: dialog.property("visible"))
            screenshots.append(capture(window, evidence, "migration-preview"))
            assert QMetaObject.invokeMethod(dialog, "reject")
            assert not (root / "new-speech").exists()
            assert not controller.restartRequired
        finally:
            controller.close()
    app.processEvents()
    return screenshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path("build/storage-governance/ui"))
    args = parser.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="shinar-storage-ui-") as directory:
        screenshots = run_probe(Path(directory), evidence)
    report = {"platform": os.environ["QT_QPA_PLATFORM"], "scale": os.environ.get("QT_SCALE_FACTOR", "1"),
              "screenshots": screenshots, "personalFilesChanged": False, "paidCalls": 0}
    (evidence / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
