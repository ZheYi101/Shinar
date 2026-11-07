"""Regression evidence for bounded work and stale GUI delivery."""

import asyncio
from types import SimpleNamespace

from lingualoop.application import LearningWorkbench
from lingualoop.core import LanguageEnum, ProficiencyLevel
from lingualoop.desktop.workspace import DesktopWorkspaceController
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider


def test_search_consumes_only_the_first_hundred_matches(monkeypatch):
    import lingualoop.application.source_loading as module

    consumed = []

    def matches(text, start, end):
        for position in range(1000):
            consumed.append(position)
            yield SimpleNamespace(start=lambda: 0, end=lambda: 1)

    monkeypatch.setattr(module.re, "compile", lambda *args: SimpleNamespace(finditer=matches))
    jobs = []
    workspace = SimpleNamespace(
        _source_full="a" * 1000,
        _source_end=1000,
        _request_job=lambda *args: jobs.append(args),
        _set_results=lambda value: None,
    )
    DesktopWorkspaceController.searchSource(workspace, "a")
    request = jobs[0][1]
    results = module.search_source(*request.args)
    assert len(results) == len(consumed) == 100


def test_new_query_invalidates_results_before_debounce():
    workspace = SimpleNamespace(
        _request={"search": 4, "document": 2},
        _source_material="book",
        _search_timer=SimpleNamespace(start=lambda: None),
    )
    DesktopWorkspaceController.scheduleSourceSearch(workspace, "new query")
    assert workspace._request["search"] == 5
    assert workspace._pending_search == (2, "book", "new query")


def test_closed_workspace_ignores_late_delivery():
    DesktopWorkspaceController._completed(SimpleNamespace(_closed=True), None, "late error")


def test_presentation_rejects_a_previous_turn():
    from lingualoop.desktop.conversation_presentation import (
        ConversationEvent,
        ConversationPresentation,
        PresentationToken,
    )

    view = ConversationPresentation()
    previous = PresentationToken("session", "first", 1, 0, "first-job")
    current = PresentationToken("session", "second", 2, 1, "second-job")
    view.apply(ConversationEvent("begin", previous))
    view.apply(ConversationEvent("begin", current))
    assert not view.apply(ConversationEvent("delta", previous, text="late"))
    assert view.apply(ConversationEvent("delta", current, text="current")) and view.snapshot.streaming_text == "current"


def test_worker_shutdown_waits_for_the_actual_executor_thread():
    from threading import Event
    from lingualoop.desktop.worker import AsyncWorker

    entered, release = Event(), Event()
    worker = AsyncWorker()

    def blocking():
        entered.set()
        release.wait(2)

    async def operation():
        await asyncio.to_thread(blocking)

    async def cleanup():
        pass

    worker.submit(operation)
    assert entered.wait(2)
    future = worker.begin_shutdown(cleanup)
    assert not future.done()
    release.set()
    worker.close(cleanup)
    assert not worker._thread.is_alive()


def test_cancelled_blocking_job_reaps_its_owned_process(monkeypatch):
    import lingualoop.infrastructure.blocking_jobs as module

    stopped = []
    original = module._stop

    async def observed(process, cancel, grace):
        await original(process, cancel, grace)
        stopped.append(not process.is_alive())

    monkeypatch.setattr(module, "_stop", observed)

    async def run():
        task = asyncio.create_task(
            module.run_blocking(
                module.BlockingRequest("search", ("abc " * 500000, 2000000, "absent"))
            )
        )
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert stopped == [True]


def test_shutdown_error_is_reported_and_cleanup_can_be_retried():
    import pytest
    from lingualoop.desktop.worker import AsyncWorker

    worker = AsyncWorker()

    async def failed():
        raise RuntimeError("cleanup_failed")

    async def cleanup():
        pass

    with pytest.raises(RuntimeError, match="cleanup_failed"):
        worker.begin_shutdown(failed).result(timeout=2)
    worker.close(cleanup)
    assert not worker._thread.is_alive()


def test_cli_saves_material_without_authorizing_unconfirmed_text(tmp_path):
    from lingualoop.cli import ConsoleSessionApp

    async def run():
        work = LearningWorkbench(MockLearningLLMProvider(), event_store=SQLiteStore(tmp_path / "cli.db"))
        responses = iter(["Book", "english", "english", "chinese", "B1", "A short story.", ".", ""])
        app = ConsoleSessionApp(work, input_fn=lambda prompt: next(responses), output_fn=lambda text: None)
        loaded = await app.handle_line("load")
        assert loaded.lines[0] == "Loaded: Book"
        assert work.material.read_through == 0 and len(work.materials) == 1
        denied = await app.handle_line("start")
        assert denied.lines[0].startswith("Error:") and work.session is None
        confirmed = await app.handle_line("scope 100")
        assert confirmed.lines == ["Reading scope confirmed: 100%."]
        started = await app.handle_line("start")
        assert started.lines[0] == "Session started."
        await work.aclose()

    asyncio.run(run())


def test_startup_restores_only_one_full_session(tmp_path):
    class ObservedStore(SQLiteStore):
        def list_sessions(self, limit=None, **kwargs):
            assert limit == 1, "startup must not deserialize the whole conversation archive"
            return super().list_sessions(limit=limit, **kwargs)

    async def run():
        store = ObservedStore(tmp_path / "history.sqlite3")
        work = LearningWorkbench(MockLearningLLMProvider(), event_store=store)
        await work.load_material(
            title="Book",
            content="Two friends meet at the station.",
            source_language=LanguageEnum.ENGLISH,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1,
        )
        for _ in range(3):
            await work.start_session()
            await work.complete_session()
        latest_id = work.session.id
        await work.aclose()
        restored = LearningWorkbench(MockLearningLLMProvider(), event_store=store)
        assert restored.session.id == latest_id
        assert len(restored.list_session_summaries()) == 3
        await restored.aclose()

    asyncio.run(run())
