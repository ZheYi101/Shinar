"""Workspace uses the same isolated, per-key compatibility policy as other settings."""
import pytest
from PySide6.QtCore import QSettings

from shinar.application import LearningWorkbench
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.workspace.controller import DesktopWorkspaceController
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


@pytest.mark.parametrize(("legacy", "current", "expected"), [
    (True, None, True), (True, False, False), (False, True, True),
])

def test_workspace_legacy_preferences_and_explicit_false(qt_app, monkeypatch, tmp_path, legacy, current, expected):
    import shinar.desktop.shell.settings as module
    stores = {name: QSettings(str(tmp_path / f"{name}.ini"), QSettings.IniFormat)
              for name in ("Shinar", "LinguaLoop")}
    stores["LinguaLoop"].setValue("sidebarCollapsed", legacy)
    if current is not None:
        stores["Shinar"].setValue("sidebarCollapsed", current)
    monkeypatch.setattr(module, "QSettings", lambda organization, section: stores[organization])
    prefs = DesktopPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    work = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(tmp_path / "library.sqlite3"))
    vm = LearningViewModel(work, "Mock", preferences=prefs)
    workspace = DesktopWorkspaceController(vm)
    try:
        assert workspace.collapsed is expected
        workspace.toggleSidebar()
        assert stores["LinguaLoop"].value("sidebarCollapsed") == legacy
        injected = QSettings(str(tmp_path / "override.ini"), QSettings.IniFormat)
        injected.setValue("sidebarCollapsed", expected)
        explicit = DesktopWorkspaceController(vm, injected)
        try:
            assert explicit.settings is injected
            assert explicit.collapsed is expected
        finally:
            explicit.close()
    finally:
        workspace.close()
        vm.close()
