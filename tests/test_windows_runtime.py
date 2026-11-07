"""Release trimming preserves native dependencies and bounds upgrade cleanup."""

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location("runtime_helper", ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native binaries")
def test_native_closure_keeps_binding_dependencies_without_unrelated_qt_modules():
    pyside = pytest.importorskip("PySide6")
    helper = module("scripts/windows_runtime.py")
    qt = Path(pyside.__file__).parent
    assert "qt6core.dll" in helper.pe_dependencies(qt / "QtCore.pyd")
    retained = helper.native_closure(qt, {qt / "QtCore.pyd"})
    assert qt / "Qt6Core.dll" in retained
    assert qt / "pyside6.abi3.dll" in retained
    assert qt / "Qt6WebEngineCore.dll" not in retained


@pytest.mark.parametrize("content", [b"", b"MZ" + b"\0" * 200, b"not a binary"])
def test_unreadable_native_dependencies_fail_before_pruning(tmp_path, content):
    path = tmp_path / "broken.dll"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="Invalid native"):
        module("scripts/windows_runtime.py").pe_dependencies(path)


def test_qt_imports_are_discovered_from_product_sources(tmp_path):
    (tmp_path / "feature.py").write_text(
        "from PySide6.QtMultimedia import QAudioSink\n"
        "from PySide6 import QtWebEngineQuick as Web\n"
        "import PySide6.QtWidgets\n",
        encoding="utf-8",
    )
    assert module("scripts/windows_runtime.py").python_qt_modules(tmp_path) == {
        "QtMultimedia",
        "QtWebEngineQuick",
        "QtWidgets",
        "QtTest",
    }


def test_trimming_refuses_an_existing_install_outside_build_root(tmp_path):
    app = tmp_path / "installed/LinguaLoop"
    app.mkdir(parents=True)
    keep = app / "personal-note.txt"
    keep.write_text("retain", encoding="utf-8")
    with pytest.raises(ValueError, match="restricted"):
        module("scripts/windows_runtime.py").trim_runtime(app, build_root=tmp_path / "build")
    assert keep.read_text() == "retain"


def test_upgrade_cleanup_only_removes_listed_retired_files(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("obsolete.dll", "required.dll", "user-note.txt"):
        (runtime / name).write_text("retain unless retired", encoding="utf-8")
    removed = module("packaging/windows/cleanup_runtime.py").cleanup(
        tmp_path,
        {
            "policy": "windows-slim-v1",
            "retired": ["obsolete.dll", "already-absent.dll"],
            "retained": ["required.dll"],
        },
    )
    assert removed == 1 and not (runtime / "obsolete.dll").exists()
    assert (runtime / "required.dll").is_file() and (runtime / "user-note.txt").is_file()


@pytest.mark.parametrize("invalid", ["../outside", "C:\\outside.dll", "/outside", "required.dll", "REQUIRED.dll"])
def test_cleanup_rejects_entire_invalid_plan_before_deleting_anything(tmp_path, invalid):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    original = runtime / "obsolete.dll"
    original.write_text("keep on error", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid retired"):
        module("packaging/windows/cleanup_runtime.py").cleanup(
            tmp_path,
            {
                "policy": "windows-slim-v1",
                "retired": ["obsolete.dll", invalid],
                "retained": ["required.dll"],
            },
        )
    assert original.read_text() == "keep on error"
