"""Refactors preserve QML-facing metadata, independent of Python helper placement."""

import json
from pathlib import Path

from shinar.desktop.presentation.viewmodel import LearningViewModel
from shinar.desktop.workspace.controller import DesktopWorkspaceController
from shinar.desktop.speech_library.viewmodel import SpeechLibraryViewModel
from tests.support.qt_contract import qt_contract
from tests.support.state_boundaries import state_boundary_violations


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
