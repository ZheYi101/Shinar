import asyncio

import pytest

from shinar.application import LearningWorkbench
from shinar.core import LanguageEnum as L, ProficiencyLevel, MaterialAnalysis
from shinar.infrastructure import SQLiteStore
from shinar.providers.mock import LegacyMockLearningLLMProvider


class Counted(LegacyMockLearningLLMProvider):
    def __init__(self, identity='model-a'):
        self.calls = 0
        self.preparation_cache_identity = identity

    async def analyze_material(self, **kwargs):
        self.calls += 1
        return await super().analyze_material(**kwargs)


async def load(work, content='Two friends met at the station.', target=L.ENGLISH):
    return await work.load_material(title='Book', content=content, source_language=L.ENGLISH,
        target_language=target, native_language=L.CHINESE, learner_level=ProficiencyLevel.B1)


def test_reimport_after_restart_reuses_analysis_and_keeps_session(tmp_path):
    async def run():
        path = tmp_path / 'library.sqlite3'
        first = Counted()
        work = LearningWorkbench(first, event_store=SQLiteStore(path))
        original = await load(work)
        await work.start_session()
        await work.send_message('I liked their decision.')
        await work.complete_session()
        session_id = work.session.id
        await work.aclose()
        second = Counted()
        restored = LearningWorkbench(second, event_store=SQLiteStore(path))
        again = await load(restored)
        assert second.calls == 0 and first.calls == 1
        assert again.id == original.id and len(restored.materials) == 1
        assert restored.session.id == session_id and len(restored.session.messages) == 3
        assert again.analysis.model_dump() == original.analysis.model_dump()
        assert again.analysis_cache_key
        await restored.aclose()
    asyncio.run(run())


def test_source_language_and_model_changes_do_not_use_wrong_cache(tmp_path):
    async def run():
        store = SQLiteStore(tmp_path / 'cache.sqlite3')
        first = Counted()
        work = LearningWorkbench(first, event_store=store)
        english = await load(work)
        japanese = await load(work, target=L.JAPANESE)
        changed = await load(work, content='Two friends returned home.')
        assert first.calls == 3
        assert len({english.analysis_cache_key, japanese.analysis_cache_key, changed.analysis_cache_key}) == 3
        other = Counted('model-b')
        restored = LearningWorkbench(other, event_store=store)
        await load(restored)
        assert other.calls == 0  # Reimport preserves an existing completed book, even after a model switch.
        await restored.analyze_current_material()  # Explicit analysis uses the new model's separate cache.
        assert other.calls == 1
        await restored.aclose()
        await work.aclose()
    asyncio.run(run())


def test_reimport_preserves_custom_topic_added_after_cached_preparation(tmp_path):
    async def run():
        store = SQLiteStore(tmp_path / 'custom-topic.sqlite3')
        first = LearningWorkbench(Counted(), event_store=store)
        await load(first)
        await first.start_session(custom_topic='The friends choosing to meet again')
        topic_id = first.session.topic.id
        await first.aclose()
        provider = Counted()
        reopened = LearningWorkbench(provider, event_store=store)
        await load(reopened)
        assert provider.calls == 0
        assert topic_id in {topic.id for topic in reopened.material.analysis.topics}
        assert reopened.session.topic.id == topic_id
        await reopened.aclose()
    asyncio.run(run())


def test_cached_partial_import_waits_for_explicit_continue_and_resumes(tmp_path):
    class FailsOnce(Counted):
        async def analyze_material(self, **kwargs):
            if self.calls == 1:
                self.calls += 1
                raise RuntimeError('interrupted')
            return await super().analyze_material(**kwargs)
    async def run():
        store = SQLiteStore(tmp_path / 'partial.sqlite3')
        provider = FailsOnce()
        work = LearningWorkbench(provider, event_store=store)
        text = '章の出来事。\n' * 5000
        with pytest.raises(RuntimeError): await load(work, text)
        original_id = work.material.id
        restored = LearningWorkbench(provider, event_store=store)
        material = await load(restored, text)
        assert provider.calls == 2 and len(material.analysis.chunks) == 1
        assert material.id == original_id and not material.analysis.preparation_complete
        await restored.analyze_current_material()
        assert provider.calls == 4 and restored.material.analysis.preparation_complete
        await restored.aclose()
        await work.aclose()
    asyncio.run(run())


def test_partial_save_does_not_replace_a_complete_cache(tmp_path):
    store = SQLiteStore(tmp_path / 'cache.sqlite3')
    complete = MaterialAnalysis(summary='Integrated story', preparation_complete=True, overview_complete=True)
    store.save_preparation_cache('key', 'source', complete)
    store.save_preparation_cache('key', 'source', MaterialAnalysis(summary='A section', preparation_complete=False))
    assert store.get_preparation_cache('key') == complete


def test_history_selection_restores_older_thread_without_changing_recency(tmp_path):
    async def run():
        store = SQLiteStore(tmp_path / 'history.sqlite3')
        work = LearningWorkbench(Counted(), event_store=store)
        await load(work)
        await work.start_session(topic_id=work.material.analysis.topics[0].id)
        await work.send_message('FIRST READER VIEW')
        await work.complete_session()
        first_id = work.session.id
        await work.start_session(topic_id=work.material.analysis.topics[1].id)
        await work.send_message('SECOND READER VIEW')
        second_id = work.session.id
        work.select_session(first_id)
        assert work.session.messages[1].content == 'FIRST READER VIEW'
        assert work.session.status.value == 'completed'
        assert [s.id for s in work.sessions] == [second_id, first_id]
        await work.aclose()
        reopened = LearningWorkbench(Counted(), event_store=store)
        assert len(reopened.sessions) == 2
        reopened.select_session(first_id)
        assert reopened.session.messages[1].content == 'FIRST READER VIEW'
        await reopened.aclose()
    asyncio.run(run())


def test_offline_library_reimport_cannot_erase_prepared_material(tmp_path):
    from shinar.providers.unavailable import UnavailableLearningLLMProvider
    async def run():
        store = SQLiteStore(tmp_path / 'offline.sqlite3')
        online = LearningWorkbench(Counted(), event_store=store)
        prepared = await load(online)
        await online.aclose()
        offline = LearningWorkbench(UnavailableLearningLLMProvider(), event_store=store)
        same = await load(offline)
        assert same.id == prepared.id and same.analysis == prepared.analysis
        with pytest.raises(RuntimeError, match='本地整理资料会保留'): await offline.analyze_current_material()
        assert store.get_material(prepared.id).analysis == prepared.analysis
        await offline.aclose()
    asyncio.run(run())
