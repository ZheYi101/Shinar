"""The guards must reject real bypasses, independently of production spelling."""
from pathlib import Path

import pytest

from tests.support.boundaries import desktop_violations, import_cycles, private_accesses


@pytest.mark.parametrize("source", [
    "self.call._tts_error",
    "self._workbench._session_material()",
    "vm.workbench._event_store",
    "peer = vm.workbench\npeer._event_store",
    "self.peer = vm\nself.peer._draft",
    "def action(peer: LearningViewModel):\n    peer._draft = ''",
    "getattr(vm.workbench, '_event_store')",
    "peer = self.call\nsetattr(peer, '_tts_error', '')",
    "from .voice import _SpeechRoute as Route",
])
def test_private_access_bypasses_are_rejected(source):
    assert private_accesses(source)


def test_owner_fields_and_public_interfaces_are_allowed():
    assert not private_accesses("self._draft = ''\nself.call.tts_available\nself.workbench.session_material()")


def test_subpackages_are_checked(tmp_path):
    child = tmp_path / "voice"
    child.mkdir()
    (child / "controller.py").write_text("self.call._tts_error", encoding="utf-8")
    assert desktop_violations(tmp_path)[0].startswith(str(Path("voice/controller.py")))


def test_type_checking_edges_do_not_create_runtime_cycles(tmp_path):
    (tmp_path / "a.py").write_text("from .b import B", encoding="utf-8")
    other = tmp_path / "b.py"
    other.write_text("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from .a import A", encoding="utf-8")
    assert not import_cycles(tmp_path, "example")
    other.write_text("def run():\n    from .a import A", encoding="utf-8")
    assert import_cycles(tmp_path, "example")
