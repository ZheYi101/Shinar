from __future__ import annotations

import importlib.util
import asyncio
from pathlib import Path
import sys

import pytest

from shinar.application import LearningWorkbench
from shinar.core import LanguageEnum, ProficiencyLevel
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider



def test_desktop_app_module_imports_without_loading_qt() -> None:
    from shinar.desktop import app

    assert app.create_workbench
    assert app.create_engine
    assert app.parse_args([]).use_mock is False
    assert app.parse_args(["--mock"]).provider_label == "Mock 调试"
    assert app.parse_args(["--mock", "--smoke"]).smoke is True


def test_windows_craft_module_is_not_auto_loaded_into_pyside(monkeypatch, tmp_path) -> None:
    from shinar.desktop import app

    craft_qml = tmp_path / "CraftRoot" / "qml"
    (craft_qml / "org" / "kde" / "kirigami").mkdir(parents=True)
    monkeypatch.setenv("QML2_IMPORT_PATH", str(craft_qml))
    monkeypatch.setenv("SHINAR_KIRIGAMI_MODE", "auto")
    assert app.kirigami_runtime_available()
    if sys.platform == "win32":
        assert not app.kirigami_runtime_usable()


def test_desktop_missing_env_keeps_local_library_readable(monkeypatch, tmp_path) -> None:
    from shinar.desktop import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SHINAR_DATA_DIR', str(tmp_path / 'local-data'))
    for name in [
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_REASONING_MODEL",
        "OPENAI_DIALOGUE_MODEL",
    ]:
        monkeypatch.delenv(name, raising=False)

    work = app.create_workbench(use_mock=False)
    assert work._provider.display_label == '本地资料 · AI 未配置'
    with pytest.raises(RuntimeError, match='ai_service_unconfigured'):
        asyncio.run(work._provider.generate_reply())


def test_qml_review_answers_are_hidden_until_submission() -> None:
    qml_root = Path(__file__).parents[2] / "src" / "shinar" / "desktop" / "qml"
    qml = "\n".join(path.read_text(encoding="utf-8") for path in qml_root.rglob("*.qml"))

    assert "答案：" not in qml
    assert "参考答案 " in qml
    assert "answerSubmitted" in qml
    assert "workspace.materials" in qml
    assert "workspace.browseMaterial" in qml


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)
def test_viewmodel_materials_restore_from_workbench(tmp_path) -> None:
    from shinar.desktop.presentation.viewmodel import LearningViewModel

    async def seed() -> None:
        workbench = LearningWorkbench(
            MockLearningLLMProvider(),
            event_store=SQLiteStore(tmp_path / "desktop.sqlite3"),
        )
        await workbench.load_material(
            title="Restored material",
            source_language=LanguageEnum.ENGLISH,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.A2,
            content="Yesterday I went to the market.",
        )

    asyncio.run(seed())
    restored = LearningWorkbench(
        MockLearningLLMProvider(),
        event_store=SQLiteStore(tmp_path / "desktop.sqlite3"),
    )
    viewmodel = LearningViewModel(restored, "Mock 调试")

    assert viewmodel.materials[0]["title"] == "Restored material"
    viewmodel.selectMaterial(viewmodel.materials[0]["id"])
    assert "Restored material" in viewmodel.materialSummary


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)
@pytest.mark.parametrize("width,height", [(1180, 780), (360, 740), (412, 915)])
def test_qml_engine_factory_works_offscreen(monkeypatch, tmp_path, width, height) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("SHINAR_KIRIGAMI_MODE", "off")
    monkeypatch.setenv("QT_QUICK_CONTROLS_MOBILE", "1" if width < 600 else "0")
    from PySide6.QtCore import QObject, QSettings
    from PySide6.QtGui import QGuiApplication

    from shinar.desktop import app
    from shinar.desktop.presentation.viewmodel import LearningViewModel

    qt_app = QGuiApplication.instance() or QGuiApplication(["shinar-desktop-test"])
    viewmodel = LearningViewModel(LearningWorkbench(MockLearningLLMProvider(),
        event_store=SQLiteStore(tmp_path / "ui.sqlite3")), "Mock 调试")
    engine = app.create_engine(viewmodel, window_settings=QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat))

    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    root.width = width
    root.height = height
    qt_app.processEvents()
    assert root.width == width
    assert root.height == height
    for object_name in ("sourceScroll", "practiceScroll", "reviewScroll"):
        scroll = root.findChild(QObject, object_name)
        assert scroll is not None
        assert scroll.property("contentWidth") == scroll.property("availableWidth")
    assert app.desktop_dependencies_available()
    assert isinstance(app.kirigami_runtime_available(), bool)
    viewmodel.close()
    root.close()
    engine.deleteLater()
    qt_app.processEvents()
