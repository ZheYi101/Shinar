"""Shared material/scope/conversation scenarios through the real desktop flow."""

from PySide6.QtTest import QTest
from tests.support.qt import click, until


def workspace_of(window):
    return window.property("workspaceController")


def load_material(vm, title, content, source, target, native, level):
    from shinar.core import LanguageEnum, ProficiencyLevel

    vm.run_operation(
        "保存材料",
        lambda: vm.workbench.load_material(
            title=title,
            content=content,
            source_language=LanguageEnum(source),
            target_language=LanguageEnum(target),
            native_language=LanguageEnum(native),
            learner_level=ProficiencyLevel(level),
            auto_prepare=False,
        ),
        vm._after_material_loaded,
    )


def load_and_start(vm, window, *, wait=until):
    load_material(
        vm,
        "放課後の約束",
        "放課後、二人は喫茶店で話した。離れても友達でいようと約束した。",
        "japanese",
        "japanese",
        "chinese",
        "B1",
    )
    wait(lambda: not vm.busy)
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    wait(lambda: ws.documentReady)
    click(window, "readWholeMaterialButton")
    click(window, "saveScopeButton")
    wait(lambda: not vm.busy)
    assert ws.material["confirmed"]
    ws.newThreadPage()
    QTest.qWait(60)
    click(window, "startDiscussionButton")
    wait(lambda: vm.sessionActive and not vm.busy)
