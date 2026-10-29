"""PySide6/QML entry point for the desktop and Android-oriented shell."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

from lingualoop.application import LearningWorkbench
from lingualoop.cli import build_provider


# Keep DLL directory handles alive for the lifetime of the process. Windows
# otherwise removes an added DLL directory as soon as its handle is released.
_dll_directory_handles: list[Any] = []
_font_ids: dict[str, int] = {}


@dataclass(frozen=True)
class DesktopRuntimeConfig:
    use_mock: bool
    smoke: bool = False

    @property
    def provider_label(self) -> str:
        return "Mock 调试" if self.use_mock else "真实 AI"


def parse_args(argv: Sequence[str] | None = None) -> DesktopRuntimeConfig:
    parser = argparse.ArgumentParser(description="LinguaLoop 桌面端")
    parser.add_argument("--mock", action="store_true", help="使用离线 mock provider")
    parser.add_argument("--real", action="store_true", help="使用真实 OPENAI_* provider（默认）")
    parser.add_argument("--smoke", action="store_true", help="启动并加载 QML 后立即退出，用于环境检查")
    args = parser.parse_args(argv)
    if args.mock and args.real:
        parser.error("--mock 和 --real 不能同时使用")
    return DesktopRuntimeConfig(use_mock=args.mock, smoke=args.smoke)


def create_workbench(*, use_mock: bool = False) -> LearningWorkbench:
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    try:
        provider = build_provider(use_mock)
    except Exception:
        if use_mock:
            raise
        from lingualoop.providers.unavailable import UnavailableLearningLLMProvider
        provider = UnavailableLearningLLMProvider()
    return LearningWorkbench(provider)


def desktop_dependencies_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def _load_qt() -> dict[str, Any]:
    try:
        from PySide6.QtCore import QLibraryInfo, QUrl
        from PySide6.QtGui import QFont, QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError as exc:
        raise ImportError(
            "桌面端依赖尚未安装。请运行 `uv sync --extra desktop` 安装 PySide6。"
        ) from exc
    return {
        "QFont": QFont,
        "QGuiApplication": QGuiApplication,
        "QQmlApplicationEngine": QQmlApplicationEngine,
        "QUrl": QUrl,
        "QLibraryInfo": QLibraryInfo,
    }


def kirigami_runtime_available() -> bool:
    """Return whether Qt can find the KDE Kirigami QML module."""
    try:
        from PySide6.QtCore import QLibraryInfo
    except ImportError:
        return False
    roots = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))]
    for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        roots.extend(Path(item) for item in os.environ.get(key, "").split(os.pathsep) if item)
    return any((root / "org" / "kde" / "kirigami").exists() for root in roots)


def kirigami_runtime_usable() -> bool:
    """Return whether this PySide6 process can safely load Kirigami.

    On Windows, a QML module found through Craft is not automatically
    compatible with the Qt libraries bundled by the PyPI PySide6 wheel. The
    native plugin can fail with a process-level DLL entry-point error before
    Qt has a chance to report a normal QML error. Auto mode therefore only
    accepts a module shipped inside the active PySide6 installation. A
    matching system runtime can opt in with ``LINGUALOOP_KIRIGAMI_MODE=on``.
    """
    mode = os.getenv("LINGUALOOP_KIRIGAMI_MODE", "auto").strip().lower()
    if mode == "off":
        return False
    if not kirigami_runtime_available():
        return False
    if mode == "on" or os.name != "nt":
        return True

    try:
        from PySide6.QtCore import QLibraryInfo
    except ImportError:
        return False

    pyside_qml_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
    return any(
        (root / "org" / "kde" / "kirigami").exists()
        and _is_same_or_child(root / "org" / "kde" / "kirigami", pyside_qml_root)
        for root in _qml_import_roots()
    )


def _qml_import_roots() -> list[Path]:
    try:
        from PySide6.QtCore import QLibraryInfo
    except ImportError:
        return []
    roots = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))]
    for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH"):
        roots.extend(Path(item) for item in os.environ.get(key, "").split(os.pathsep) if item)
    return roots


def _is_same_or_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def create_engine(viewmodel: Any, *, window_settings=None, initial_visible: bool = True,
                  speech_library=None) -> Any:
    qt = _load_qt()
    from PySide6.QtQuickControls2 import QQuickStyle
    if QQuickStyle.name() != "Material":
        QQuickStyle.setStyle("Material")
    from PySide6.QtGui import QFontDatabase
    font_root = files("lingualoop.desktop").joinpath("qml/assets/fonts")
    for name in ("NotoSerifSC-Regular.otf", "NotoSerifJP-Regular.otf"):
        path = str(font_root.joinpath(name))
        if path not in _font_ids:
            font_id = QFontDatabase.addApplicationFont(path)
            if font_id < 0:
                raise RuntimeError(f"内置字体加载失败：{name}")
            _font_ids[path] = font_id
    _apply_default_font(qt["QGuiApplication"], qt["QFont"])
    use_kirigami = kirigami_runtime_usable() and os.getenv("LINGUALOOP_KIRIGAMI_MODE", "auto") == "on"
    if use_kirigami:
        _configure_kirigami_dll_path()
    engine = qt["QQmlApplicationEngine"]()
    from lingualoop.desktop.speech_library import SpeechLibraryViewModel
    if speech_library is None and "Mock" in viewmodel.providerLabel:
        from tempfile import TemporaryDirectory
        engine.mock_resources = TemporaryDirectory(prefix="lingualoop-ui-mock-")
        library = SpeechLibraryViewModel(Path(engine.mock_resources.name) / "speech", parent=engine)
    else:
        library = speech_library if speech_library is not None else SpeechLibraryViewModel(parent=engine)
    engine.rootContext().setContextProperty("speechLibrary", library)
    engine.speech_library = library
    if hasattr(viewmodel, "configure_local_speech"):
        viewmodel.configure_local_speech(library)
    qt["QGuiApplication"].instance().aboutToQuit.connect(library.close)
    from lingualoop.desktop.window import DesktopWindowController
    controller = DesktopWindowController(window_settings, engine)
    from lingualoop.desktop.workspace import DesktopWorkspaceController
    workspace = DesktopWorkspaceController(viewmodel, window_settings, engine)
    engine.workspace = workspace
    engine.rootContext().setContextProperty("workspace", workspace)
    qt["QGuiApplication"].instance().aboutToQuit.connect(workspace.close)
    engine.rootContext().setContextProperty("learningViewModel", viewmodel)
    engine.rootContext().setContextProperty("desktopWindow", controller)
    engine.rootContext().setContextProperty("initialWindowVisible", initial_visible)
    qml_root = files("lingualoop.desktop").joinpath("qml")
    qml_name = "Main.qml" if use_kirigami else "MainFallback.qml"
    qml_path = qml_root.joinpath(qml_name)
    engine.load(qt["QUrl"].fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        fallback = qml_root.joinpath("MainFallback.qml")
        if qml_name != "MainFallback.qml":
            engine.load(qt["QUrl"].fromLocalFile(str(fallback)))
    if not engine.rootObjects():
        raise RuntimeError("QML 页面加载失败，请参考 docs/desktop/QML_RUNTIME.md 配置 Qt runtime。")
    controller.attach(engine.rootObjects()[0])
    engine.window_controller = controller
    return engine


def _apply_default_font(qgui_application: Any, qfont: Any) -> None:
    app = qgui_application.instance()
    if app is None:
        return
    family = _preferred_ui_font_family()
    font = qfont(family)
    font.setPointSize(10)
    app.setFont(font)


def _preferred_ui_font_family() -> str:
    if os.name == "nt":
        return "Microsoft YaHei UI"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def _configure_kirigami_dll_path() -> None:
    """Make Craft's Kirigami native libraries visible to the Windows loader."""
    roots = [
        Path(item)
        for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH")
        for item in os.environ.get(key, "").split(os.pathsep)
        if item
    ]
    for root in roots:
        candidates = [root.parent / "bin", root.parent.parent / "bin"]
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            candidate_text = str(candidate)
            if candidate_text not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = candidate_text + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory") and candidate_text not in {
                getattr(handle, "name", "") for handle in _dll_directory_handles
            }:
                _dll_directory_handles.append(os.add_dll_directory(candidate_text))


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = parse_args(argv)
        qt = _load_qt()
        os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
        os.environ.setdefault("QT_QUICK_CONTROLS_MATERIAL_THEME", "Light")
        app = qt["QGuiApplication"](["lingualoop-desktop", *list(argv or sys.argv[1:])])
        from lingualoop.desktop.viewmodel import LearningViewModel

        viewmodel = LearningViewModel(create_workbench(use_mock=config.use_mock), config.provider_label)
        engine = create_engine(viewmodel)
        app.aboutToQuit.connect(viewmodel.close)
        if config.smoke:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, app.quit)
        app.aboutToQuit.connect(lambda: _keep_alive(engine, viewmodel))
        return app.exec()
    except ImportError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


def _keep_alive(_engine: Any, _viewmodel: Any) -> None:
    return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
