import asyncio

import pytest

from shinar.application import LearningWorkbench
from shinar.core.domain import LanguageEnum, ProficiencyLevel
from shinar.infrastructure import SQLiteStore
from shinar.providers.mock import MockLearningLLMProvider


async def import_and_authorize(work):
    material = await work.load_material(
        title="Bridge", content="Mira waits at the bridge. Ren leaves.",
        source_language=LanguageEnum.ENGLISH, target_language=LanguageEnum.ENGLISH,
        native_language=LanguageEnum.CHINESE, learner_level=ProficiencyLevel.B1,
        auto_prepare=False,
    )
    work.set_reading_scope(len(material.content))


@pytest.mark.parametrize("outcome", ["ready", "failed", "cancelled"])
def test_close_accepts_settled_material_tasks_from_a_closed_seed_loop(tmp_path, outcome):
    class Provider(MockLearningLLMProvider):
        closed = False

        async def prepare_source_unit(self, request):
            started.set()
            if outcome == "cancelled":
                await asyncio.Event().wait()
            if outcome == "failed":
                raise ConnectionError("offline")
            return await super().prepare_source_unit(request)

        async def aclose(self):
            self.closed = True

    provider = Provider()
    work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "seed.sqlite3"))

    async def seed():
        nonlocal started
        started = asyncio.Event()
        await import_and_authorize(work)
        if outcome == "cancelled":
            await asyncio.wait_for(started.wait(), 2)
        else:
            await work.prepare_current_material()
        return asyncio.get_running_loop()

    started = None
    loop = asyncio.run(seed())
    assert loop.is_closed()
    assert work.material.analysis.knowledge.status == {
        "ready": "ready", "failed": "failed", "cancelled": "partial",
    }[outcome]
    asyncio.run(work.aclose())
    assert provider.closed


def test_close_waits_for_material_cancellation_cleanup_before_closing_provider(tmp_path):
    class Provider(MockLearningLLMProvider):
        closed = False
        cleaned = False

        async def prepare_source_unit(self, request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await release_cleanup.wait()
                self.cleaned = True

        async def aclose(self):
            assert self.cleaned
            self.closed = True

    async def run():
        nonlocal started, cleanup_started, release_cleanup
        started, cleanup_started, release_cleanup = (asyncio.Event() for _ in range(3))
        provider = Provider()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "active.sqlite3"))
        await import_and_authorize(work)
        await asyncio.wait_for(started.wait(), 2)
        closing = asyncio.create_task(work.aclose())
        await asyncio.wait_for(cleanup_started.wait(), 2)
        assert not closing.done() and not provider.closed
        release_cleanup.set()
        await asyncio.wait_for(closing, 2)
        assert provider.cleaned and provider.closed

    started = cleanup_started = release_cleanup = None
    asyncio.run(run())
