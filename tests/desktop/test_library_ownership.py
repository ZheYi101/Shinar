"""Worker completion is data until its current owner accepts it on the GUI thread."""

from threading import Event

import pytest

from shinar.desktop.speech_library.state import CatalogProjection, LibraryOperations
from shinar.desktop.speech_library.monitor import ResourceMonitor


def test_operation_result_is_immutable_and_late_completion_cannot_finish_retry():
    owner, events = LibraryOperations(), []
    gate = Event()
    assert owner.start("first", lambda cancel, emit: gate.wait(1) or {}, events.append)
    identity = owner.snapshot.identity
    owner.cancel()
    gate.set()
    owner.wait(2)
    assert owner.snapshot.busy  # The worker never mutates the owner.
    assert owner.accept(events[0])
    assert owner.snapshot.error["code"] == "speech_setup_cancelled"
    assert owner.start("retry", lambda cancel, emit: {"rows": [{"id": "new"}]}, events.append)
    owner.wait(2)
    assert owner.snapshot.identity != identity
    assert not owner.accept(events[0])
    with pytest.raises(TypeError):
        events[-1].value["rows"][0]["id"] = "changed"
    assert owner.accept(events[-1])
    owner.close()
    assert owner.finished() and not owner.accept(events[-1])


def test_cancelled_future_is_not_a_finished_library_thread():
    owner, gate, started = LibraryOperations(), Event(), Event()

    def blocking(cancel, emit):
        started.set()
        gate.wait(2)
        return {}

    owner.start("work", blocking, lambda event: None)
    assert started.wait(1)
    owner.close()
    assert not owner.finished()
    gate.set()
    owner.wait(2)
    assert owner.finished()


def test_catalog_snapshot_does_not_leak_nested_mutable_rows():
    owner = CatalogProjection()
    data = {"rows": [{"id": "old", "details": ["original"]}]}
    owner.apply(data)
    data["rows"][0]["details"].append("changed")
    assert owner.snapshot["rows"][0]["details"] == ("original",)
    with pytest.raises(TypeError):
        owner.snapshot["rows"][0]["id"] = "changed"
    owner.defer_refresh()
    owner.defer_refresh()
    assert owner.take_refresh() and not owner.take_refresh()


def test_disabled_resource_monitor_rejects_late_scan_and_waits_for_actual_thread(monkeypatch):
    import shinar.desktop.speech_library.monitor as module

    owner, events, gate, started = ResourceMonitor(), [], Event(), Event()

    def scan(pids, gpu):
        started.set()
        gate.wait(2)
        return {"pids": pids, "gpus": [{"index": 0}]}

    monkeypatch.setattr(module, "resource_snapshot", scan)
    owner.enable(True)
    owner.poll([1], [2], events.append)
    assert started.wait(1)
    owner.enable(False)
    assert not owner.finished()
    gate.set()
    owner.wait(2)
    assert owner.finished() and not owner.accept(events[0])
    owner.enable(True)
    owner.poll([3], [4], events.append)
    owner.wait(2)
    assert owner.accept(events[-1])
    assert owner.snapshot["pids"] == (3,)
    owner.close()
    assert not owner.accept(events[-1])
