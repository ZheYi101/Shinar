"""Qt fixtures scoped to desktop tests; core collection stays Qt independent."""

import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6")


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6")
    from tests.support.qt import ensure_app

    return ensure_app()


@pytest.fixture
def desktop(qt_app, tmp_path):
    from tests.support.desktop import desktop_scene

    with desktop_scene(qt_app, tmp_path) as scene:
        yield scene


@pytest.fixture
def library_desktop(qt_app, tmp_path):
    from tests.support.speech_library import speech_library_scene

    with speech_library_scene(tmp_path) as scene:
        yield scene
