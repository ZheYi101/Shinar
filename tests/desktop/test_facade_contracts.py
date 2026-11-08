"""Refactors preserve QML-facing metadata, independent of Python helper placement."""

import json
from pathlib import Path

from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.workspace.controller import DesktopWorkspaceController
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from tests.support.qt_contract import qt_contract
from tests.support.state_boundaries import state_boundary_violations, collaborator_violations


def test_public_qt_facade_contracts_are_unchanged():
    expected = json.loads((Path(__file__).parent / "fixtures/facade-contracts.json").read_text(encoding="utf-8"))
    for kind in (LearningViewModel, DesktopWorkspaceController, SpeechLibraryViewModel):
        assert qt_contract(kind) == expected[kind.__name__]


def test_shared_state_debt_only_decreases():
    root = Path(__file__).resolve().parents[2]
    debt = json.loads((Path(__file__).parent / "fixtures/state-debt.json").read_text(encoding="utf-8"))
    current = {
        path.relative_to(root).as_posix(): state_boundary_violations(path.read_text(encoding="utf-8"))
        for area in ("presentation", "workspace", "speech_library")
        for path in (root / "src/shinar/desktop" / area).rglob("*.py")
    }
    for path, violations in current.items():
        assert set(violations) <= set(debt.get(path, [])), (path, violations)


def test_state_guard_recognizes_mixin_and_foreign_signal_writes():
    source = "class BadMixin:\n def update(self):\n  self._draft = ''\n  self._rows[0] = {}\n  self.vm.materialChanged.emit()\n"
    assert len(state_boundary_violations(source)) == 3
    aliased = "class Controller:\n def refresh(self):\n  target = self.vm\n  signal = target.uiChanged\n  signal.emit()\n"
    assert state_boundary_violations(aliased) == ["Controller.refresh:signal:signal.emit"]


def test_plain_state_owners_do_not_import_qt_or_hold_complete_facades():
    root = Path(__file__).resolve().parents[2] / "src/shinar/desktop"
    modules = {
        "presentation": ("editing", "material_projection", "review_projection", "operations"),
        "speech_library": ("state", "monitor", "work"),
        "workspace": ("import_editor", "navigation", "reading_state", "jobs", "task_identity"),
    }
    for area, names in modules.items():
        for name in names:
            path = root / area / (name + ".py")
            assert not collaborator_violations(path.read_text(encoding="utf-8")), path


def test_state_owner_guard_rejects_qt_aliases_and_complete_facade_references():
    source = "from PySide6.QtCore import QObject\nfrom other import LearningViewModel as VM\nclass Bad:\n def __init__(self, context: VM):\n  self._vm = context\n"
    assert collaborator_violations(source) == ["facade-parameter", "facade-reference", "qt-import"]


def test_facades_cannot_reintroduce_writable_transient_field_aliases():
    import ast
    root = Path(__file__).resolve().parents[2] / "src/shinar/desktop"
    fields = {
        "presentation/viewmodel.py": {"_draft", "_draft_revision", "_session_drafts", "_presentation_generation",
                                      "_selected_topic", "_custom_topic", "_topic_filter", "_topic_search",
                                      "_feedback_items", "_review_items", "_busy", "_status", "_retry_operation"},
        "workspace/controller.py": {"_route", "_browsing", "_collapsed", "_expanded", "_materials", "_threads",
                                    "_states", "_opening", "_import_title", "_import_text", "_imported",
                                    "_request", "_source_snapshot", "_preview", "_results", "_sections"},
        "speech_library/viewmodel.py": {"_rows", "_hardware", "_runtimes", "_storage", "_last_setup_error",
                                       "_progress", "_busy", "_status", "_resources", "_language", "_scenario"},
    }
    for name, forbidden in fields.items():
        for node in ast.walk(ast.parse((root / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                assert not (node.attr in forbidden and ast.unparse(node.value) == "self"), (name, node.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"setattr", "delattr"}:
                assert not (len(node.args) > 1 and ast.unparse(node.args[0]) == "self"
                            and isinstance(node.args[1], ast.Constant) and node.args[1].value in forbidden)
