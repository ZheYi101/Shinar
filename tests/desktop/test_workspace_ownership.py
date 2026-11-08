"""Independent source identities and import/navigation/reading state ownership."""

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from shinar.core import MaterialSourceType
from shinar.desktop.workspace.import_editor import ImportEditor
from shinar.desktop.workspace.navigation import WorkspaceNavigation
from shinar.desktop.workspace.jobs import WorkspaceJobs
from shinar.desktop.workspace.task_identity import TaskLane
from shinar.infrastructure.blocking_jobs import BlockingRequest
from shinar.infrastructure.material_import import ImportedMaterial
from tests.support.qt import until
from tests.support.scenarios import load_and_start, workspace_of


def test_import_preserves_retyped_title_and_freezes_file_metadata():
    owner = ImportEditor("english")
    owner.title("user title")
    previous = owner.inspect()
    owner.title("different title")
    owner.title("user title")
    imported = ImportedMaterial(
        "file title", "raw", "normalized", MaterialSourceType.TEXT, "new.txt", ["note"]
    )
    owner.receive(imported, previous)
    imported.diagnostics.append("outside edit")
    assert owner.snapshot.title == "user title" and owner.filename == "new.txt"
    assert owner.snapshot.file.diagnostics == ("note",)
    with pytest.raises(FrozenInstanceError):
        owner.snapshot.file.title = "bypass"
    detached = owner.snapshot.file.material()
    detached.diagnostics.append("detached")
    assert owner.snapshot.file.diagnostics == ("note",)


def test_source_task_lanes_reject_old_results_independently():
    submitted, results = [], []
    jobs = WorkspaceJobs(
        lambda task, op: submitted.append((task, op)), lambda _: None, lambda _: None
    )
    document, search, imports = TaskLane(), TaskLane(), TaskLane()
    for lane in (document, search, imports):
        jobs.start(lane, lambda: None, results.append, results.append, "book", "thread")
    search.invalidate()
    assert jobs.deliver(submitted[0][0], "document", "")
    assert not jobs.deliver(submitted[1][0], "old search", "")
    assert jobs.deliver(submitted[2][0], "file", "")
    assert results == ["document", "file"]
    jobs.start(document, lambda: None, results.append, results.append, "book", "thread")
    jobs.close()
    assert not jobs.deliver(submitted[-1][0], "late completion", "")


def test_source_inputs_are_detached_before_background_work(monkeypatch):
    import shinar.desktop.workspace.jobs as module

    observed, operations = [], []

    async def run(request):
        return request.args[0]

    monkeypatch.setattr(module, "run_blocking", run)
    jobs = WorkspaceJobs(
        lambda task, op: operations.append((task, op)), lambda _: None, lambda _: None
    )
    data = {"content": ["original"]}
    jobs.start(
        TaskLane(),
        BlockingRequest("source", (data,)),
        observed.append,
        observed.append,
        "book",
        "thread",
    )
    data["content"].append("edited")
    task, operation = operations.pop()
    jobs.deliver(task, asyncio.run(operation()), "")
    assert observed == [{"content": ["original"]}]


def test_navigation_snapshot_and_qml_projection_have_no_shared_containers():
    owner = WorkspaceNavigation("library", "book", False)
    rows = [{"id": "book", "threads": [{"id": "one"}]}]
    owner.models([], rows)
    rows[0]["threads"].append({"id": "outside"})
    assert len(owner.snapshot.materials[0]["threads"]) == 1
    with pytest.raises(TypeError):
        owner.snapshot.materials[0]["threads"][0]["id"] = "changed"
    owner.editor(3, 10.0)
    owner.remember("thread")
    owner.editor(7, 50.0)
    owner.restore("thread", 0)
    assert (owner.snapshot.cursor, owner.snapshot.scroll) == (3, 10.0)


def test_scope_and_preview_restore_current_selection_and_reading_position(desktop):
    vm, window, *_ = desktop
    load_and_start(vm, window)
    vm.stopPlayback()
    ws = workspace_of(window)
    ws.toggleSource()
    until(lambda: ws.documentReady)
    ws.selectSource(0, 5)
    selected = ws.snapshot()
    ws.saveSourceScroll(77.0)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    until(lambda: ws.documentReady)
    ws.locatePercent(100)
    ws.cancelScope()
    ws.navigate("chat")
    until(lambda: ws.documentReady)
    assert ws.snapshot() == selected and ws.sourceScroll == 77.0
    vm.draft = "Discuss this passage."
    vm.sendMessage(vm.draft)
    until(lambda: not vm.busy)
    ws.selectSource(5, 10)
    current = ws.snapshot()
    ws.saveSourceScroll(88.0)
    ws.previewMessage(vm.messages[1]["id"])
    until(lambda: ws.documentReady)
    ws.saveSourceScroll(999.0)
    ws.closePreview()
    until(lambda: ws.documentReady)
    assert ws.snapshot() == current and ws.sourceScroll == 88.0
    original_thread = vm.workbench.session.id
    ws.newThreadPage()
    ws.startThread()
    until(lambda: not vm.busy)
    ws.openThread(original_thread)
    until(lambda: ws.documentReady)
    assert ws.snapshot() == current and ws.sourceScroll == 88.0
