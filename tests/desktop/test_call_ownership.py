"""The non-QObject call owners reject stale work and expose immutable snapshots."""
import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from shinar.desktop.voice.continuous.coordinator import CallCoordinator
from shinar.desktop.voice.continuous.preparation import CallPreparation
from shinar.desktop.voice.continuous.state import CallEvent
from shinar.desktop.presentation.conversation_presentation import PresentationToken



class Runtime:
    def __init__(self, root):
        self.root = root
        self.tasks, self.events, self.presented = [], [], []
        self.worker = SimpleNamespace(cancel_job=lambda job: None)
        self.voice_pending = self.operation_busy = False
        self.session_active = True
        self.bridge = SimpleNamespace(open=lambda: None, close=lambda: None)
        self.runner = None
        self.timings = {}

    def notify(self): pass
    def components_changed(self): pass
    def storage_changed(self): pass
    def suspend_preflight(self): pass
    def request_permission(self, continuation, *, starting=False): pass
    def speak_enabled(self): return False
    def new_token(self, task): return PresentationToken("session", "", 1, 0, task)
    def present(self, event): self.presented.append(event)
    def emit(self, identity, kind, value=None, generation=0):
        self.events.append(CallEvent(identity, kind, generation, value))
    def post(self, operation):
        self.tasks.append(asyncio.create_task(operation()))
        return str(len(self.tasks))


def test_call_state_is_immutable_and_old_identity_generation_and_close_are_rejected(tmp_path):
    runtime = Runtime(tmp_path)
    preparation = CallPreparation(runtime)
    call = CallCoordinator(runtime, preparation)
    call.start()
    first = call.snapshot.identity
    call.start()
    identity = call.snapshot.identity
    assert first != identity
    call.handle(CallEvent(first, "connected", value=(False, {})))
    assert call.snapshot.connection == "off"
    call.handle(CallEvent(identity, "connected", value=(False, {})))
    call.handle(CallEvent(identity, "generating", 2))
    current = call.snapshot
    with pytest.raises(FrozenInstanceError):
        current.reply = "idle"
    call.handle(CallEvent(identity, "reply_failed", 1))
    assert call.snapshot == current
    call.close()
    closed = call.snapshot
    call.handle(CallEvent(identity, "connected", value=(True, {})))
    call.start()
    assert call.snapshot == closed and closed.closed


def test_preparation_failure_retry_cancel_and_late_completion_never_start_a_call(monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.preparation as module
    async def run():
        runtime = Runtime(tmp_path)
        preparation = CallPreparation(runtime)
        operations = []
        async def fail(request, **kwargs):
            raise RuntimeError("synthetic")
        monkeypatch.setattr(module, "run_blocking", fail)
        preparation.start()
        call = CallCoordinator(runtime, preparation)
        call.start()
        assert not call.snapshot.identity and call.snapshot.connection == "off"
        await asyncio.gather(*runtime.tasks)
        preparation.handle(runtime.events[-1])
        assert preparation.snapshot.failed and not preparation.snapshot.active
        failed = preparation.snapshot.identity
        async def success(request, **kwargs):
            operations.append(request.operation)
            await asyncio.sleep(0)
        monkeypatch.setattr(module, "run_blocking", success)
        monkeypatch.setattr(preparation, "refresh_storage", lambda: None)
        preparation.start()
        assert preparation.snapshot.identity != failed
        await asyncio.gather(*runtime.tasks)
        for event in runtime.events:
            preparation.handle(event)
        assert not preparation.snapshot.failed and not preparation.snapshot.active
        assert operations == ["runtime", "continuous_assets", "server"]
        assert not runtime.presented
        preparation.start()
        identity = preparation.snapshot.identity
        preparation.cancel()
        before = preparation.snapshot
        assert not preparation.handle(CallEvent(identity, "setup_prepared"))
        assert preparation.snapshot == before
        preparation.close()
        preparation.start()
        await asyncio.gather(*runtime.tasks)
        assert not preparation.snapshot.active
    asyncio.run(run())


def test_changing_storage_clears_old_failure_and_rejects_completion(monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.preparation as module
    from shinar.desktop.voice.continuous.state import PreparationSnapshot

    async def run():
        runtime = Runtime(tmp_path / "old")
        preparation = CallPreparation(runtime)

        async def fail(request, **kwargs):
            raise RuntimeError("offline")

        monkeypatch.setattr(module, "run_blocking", fail)
        preparation.start()
        old_identity = preparation.snapshot.identity
        await asyncio.gather(*runtime.tasks)
        preparation.handle(runtime.events[-1])
        assert preparation.snapshot.failed and preparation.snapshot.error
        runtime.root = tmp_path / "new"
        preparation.root_changed(runtime.root)
        assert preparation.snapshot == PreparationSnapshot()
        assert not preparation.handle(CallEvent(old_identity, "setup_prepared"))
        assert preparation.snapshot == PreparationSnapshot()
        await asyncio.gather(*runtime.tasks)

    asyncio.run(run())


def test_cleaning_download_cache_does_not_budget_installed_components_again(monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.preparation as module

    monkeypatch.setattr(module, "runtime_plan", lambda *args: SimpleNamespace(download_bytes=0, disk_bytes=0))
    monkeypatch.setattr(module, "ModelStore", lambda root: SimpleNamespace(installed=lambda package: True))
    preparation = CallPreparation(Runtime(tmp_path))
    assert not (tmp_path / "downloads").exists()
    assert preparation.sizes() == {"downloadMiB": 0, "requiredFreeMiB": 0}


def test_preparation_reuses_only_the_original_legacy_root_on_explicit_start(monkeypatch, tmp_path):
    import shinar.desktop.voice.continuous.preparation as module

    async def run():
        runtime = Runtime(tmp_path / "selected")
        runtime.legacy_root = tmp_path / "legacy"
        runtime.legacy_root.mkdir()
        calls = []

        async def blocking(request, **kwargs):
            calls.append(request)
            await asyncio.sleep(0)

        monkeypatch.setattr(module, "run_blocking", blocking)
        preparation = CallPreparation(runtime)
        assert not calls and not runtime.root.exists()
        preparation.start()
        original = runtime.legacy_root
        runtime.legacy_root = tmp_path / "changed-after-submit"
        await asyncio.gather(*runtime.tasks)
        assert [request.operation for request in calls] == [
            "continuous_reuse", "runtime", "continuous_assets", "server",
        ]
        assert calls[0].args == (original, runtime.root)
        assert not runtime.presented

    asyncio.run(run())
