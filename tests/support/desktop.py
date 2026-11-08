"""Isolated desktop scenario with deterministic ownership and cleanup."""

import os
from contextlib import contextmanager
from unittest.mock import patch
from PySide6.QtCore import QObject, QSettings
from PySide6.QtTest import QTest
from shinar.application import LearningWorkbench
from shinar.desktop.app import create_engine
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.infrastructure import SQLiteStore
from tests.support.audio import TrackedProvider, FakeSpeech, FakeAudio


@contextmanager
def desktop_scene(qt_app, tmp_path):
    with patch.dict(os.environ, {"SHINAR_KIRIGAMI_MODE": "off"}):
        yield from _desktop_scene(qt_app, tmp_path)


def _desktop_scene(qt_app, tmp_path):
    provider, speech, audio = TrackedProvider(), FakeSpeech(), FakeAudio()
    database = tmp_path / "workflow.sqlite3"
    workbench = LearningWorkbench(provider, event_store=SQLiteStore(database))
    prefs = DesktopPreferences(
        QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    )
    vm = LearningViewModel(
        workbench,
        "Mock 调试",
        preferences=prefs,
        stt_provider=speech,
        tts_provider=speech,
        audio_controller=audio,
    )
    engine = create_engine(
        vm, window_settings=QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    )
    window = engine.rootObjects()[0]
    window.setProperty("width", 1180)
    window.setProperty("height", 900)
    window.requestActivate()
    QTest.qWait(50)
    scaffold = next(
        obj
        for obj in window.findChildren(QObject)
        if obj.metaObject().indexOfProperty("currentPage") >= 0
    )
    try:
        yield vm, window, scaffold, provider, speech, audio, database
    finally:
        vm.close()
        assert not vm._worker._thread or not vm._worker._thread.is_alive()
        assert audio.cleared
        window.close()
        window.property("workspaceController").close()
        engine.deleteLater()
        qt_app.processEvents()
