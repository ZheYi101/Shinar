import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from lingualoop.application.material_preparation import prepare_material
from lingualoop.core import LanguageEnum, LearningMaterial, SessionUserProfile
from lingualoop.providers import MockLearningLLMProvider
from lingualoop.providers.openai_compatible import OpenAICompatibleLLMProvider, OpenAICompatibleLLMSettings


def profile():
    return SessionUserProfile(profile_level='B2', target_language='english', native_language='chinese')


def test_parallel_sections_keep_order_and_reuse_overview():
    class Parallel(MockLearningLLMProvider):
        preparation_concurrency = 3
        calls = 0
        synthesis_calls = 0
        async def analyze_material_section(self, **kwargs):
            self.calls += 1
            await asyncio.sleep(0.03 if 'section 1/' in kwargs['material'].title else 0)
            return await super().analyze_material(**kwargs)
        async def synthesize_material(self, *, sections, **kwargs):
            self.synthesis_calls += 1
            return sections[-1].model_copy(update={'summary': 'Whole story including the ending', 'outline': ['opening', 'ending']})
    async def run():
        provider = Parallel()
        material = LearningMaterial(title='Novel', source_language=LanguageEnum.ENGLISH, content='章の出来事。\n' * 5000)
        snapshots = []
        async def persist(analysis): snapshots.append(analysis)
        result = await prepare_material(provider, material, profile(), persist)
        assert result.overview_complete and result.preparation_complete
        assert result.summary == 'Whole story including the ending'
        assert result.chunks[0].start_char == 0 and result.chunks[-1].end_char == len(material.content)
        assert all(a.end_char == b.start_char for a, b in zip(result.chunks, result.chunks[1:]))
        assert all(c.start_char <= d.start_char for snapshot in snapshots for c, d in zip(snapshot.chunks, snapshot.chunks[1:]))
        calls = provider.calls
        material.analysis = result
        again = await prepare_material(provider, material, profile())
        assert provider.calls == calls and provider.synthesis_calls == 1
        assert [c.id for c in again.chunks] == [c.id for c in result.chunks]
        material.content += '新しい結末。'
        changed = await prepare_material(provider, material, profile())
        assert provider.synthesis_calls == 2 and provider.calls > calls
        assert changed.chunks[-1].end_char == len(material.content)
    asyncio.run(run())


def test_failed_synthesis_resumes_saved_sections_without_repaying():
    class Interrupted(MockLearningLLMProvider):
        calls = 0
        synthesis_calls = 0
        async def analyze_material(self, **kwargs):
            self.calls += 1
            return await super().analyze_material(**kwargs)
        async def synthesize_material(self, *, sections, **kwargs):
            self.synthesis_calls += 1
            if self.synthesis_calls == 1: raise RuntimeError('temporary')
            return sections[-1]
    async def run():
        provider = Interrupted()
        material = LearningMaterial(title='Novel', source_language=LanguageEnum.JAPANESE, content='章の出来事。\n' * 5000)
        async def persist(analysis): material.analysis = analysis
        with pytest.raises(RuntimeError): await prepare_material(provider, material, profile(), persist)
        assert material.analysis.chunks and not material.analysis.preparation_complete
        calls = provider.calls
        result = await prepare_material(provider, material, profile(), persist)
        assert result.overview_complete and provider.calls == calls
    asyncio.run(run())


def test_whole_book_json_failure_retries_with_all_sections(monkeypatch):
    deadlines = []
    wait_for = asyncio.wait_for
    async def record_deadline(awaitable, timeout):
        deadlines.append(timeout)
        return await wait_for(awaitable, timeout)
    monkeypatch.setattr(asyncio, 'wait_for', record_deadline)
    class Client:
        def __init__(self, valid): self.valid, self.calls = valid, []
        async def ainvoke(self, messages, **kwargs):
            self.calls.append(messages)
            return AIMessage(content='invalid json' if len(self.calls) == 1 else self.valid)
    async def run():
        material = LearningMaterial(title='Book', source_language=LanguageEnum.JAPANESE, content='二人が駅へ行った。')
        section = await MockLearningLLMProvider().analyze_material(material=material,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        section.outline = ['opening', 'ending']
        client = Client(section.model_dump_json())
        settings = OpenAICompatibleLLMSettings(api_key=SecretStr('test'), base_url='https://example.test/v1', reasoning_model='pro')
        provider = OpenAICompatibleLLMProvider(settings, reasoning_client=client, dialogue_client=client)
        result = await provider.synthesize_material(material=material, sections=[section, section],
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert result.topics and len(client.calls) == 2
        notes = json.loads(client.calls[0][-1].content)['ordered_sections']
        assert len(notes) == 2 and notes[-1]['outline'][-1] == 'ending'
        assert deadlines == [600, 600]
        await provider._invoke_text(client, [])
        assert deadlines[-1] == 240
    asyncio.run(run())


def test_dialogue_selects_late_prepared_detail_without_reading_raw_book():
    from lingualoop.core import MaterialAnalysis, PreparedChunk, DiscussionTopic, AnswerBranch
    from lingualoop.providers.openai_compatible import _compact_reply_packet
    from lingualoop.core.material_context import _terms
    quote = 'The lighthouse was empty.'
    branch = AnswerBranch(user_intent='Why return to the lighthouse?', response_points=['Mira returns after the storm to keep her promise.'],
        suggested_reply='Her promise matters more than safety.', follow_up='Did that change your view of her?', source_excerpts=[quote])
    topic = DiscussionTopic(title='The lighthouse promise', opening_question='Why did Mira return?', source_excerpt=quote, answer_branches=[branch])
    ending = MaterialAnalysis(summary='The ending reverses Mira’s earlier decision.', topics=[topic])
    material = LearningMaterial(title='Whole novel', source_language='english', content='RAW_BOOK_MUST_NOT_BE_SENT' * 30000)
    material.analysis = MaterialAnalysis(summary='Opening, conflict and ending.', chunks=[
        PreparedChunk(id=f'part-{i}', start_char=i * 1000, end_char=(i+1) * 1000, summary='An unrelated journey',
            source_excerpt='An unrelated journey', analysis_payload=MaterialAnalysis(summary='A journey').model_dump(mode='json')) for i in range(30)] + [
        PreparedChunk(id='last-part', start_char=30000, end_char=31000, summary=ending.summary,
            source_excerpt=quote, analysis_payload=ending.model_dump(mode='json'))])
    packet = _compact_reply_packet(material, topic.model_dump(), None, 'Why did Mira return to the lighthouse?')
    assert any(item.get('section') == 31 for item in packet['relevant_prepared_knowledge'])
    assert material.analysis.chunks[-1].id == 'last-part'
    assert 'last-part' not in json.dumps(packet)
    assert any('keep her promise' in point for item in packet['relevant_prepared_knowledge'] for point in item['points'])
    assert 'RAW_BOOK_MUST_NOT_BE_SENT' not in json.dumps(packet)
    assert 'li' not in _terms('lighthouse') and 'lighthouse' in _terms('lighthouse')
    indirect = _compact_reply_packet(material, topic.model_dump(), None, 'I keep thinking about that final scene.')
    assert indirect['section_overview'][-1]['summary'] == ending.summary
    assert indirect['section_coverage'] == {'total': 31, 'included': 31, 'sampled': False}


def test_reader_stance_survives_long_conversation_and_revision_is_explicit():
    from lingualoop.core import Message, MessageRole, PracticeInstruction
    client = object()
    provider = OpenAICompatibleLLMProvider(OpenAICompatibleLLMSettings(api_key=SecretStr('test'),
        base_url='https://example.test/v1', reasoning_model='pro'), reasoning_client=client, dialogue_client=client)
    history = [Message(role=MessageRole.USER, content='EARLY_STANCE: the narrator manipulates us.')]
    history += [Message(role=MessageRole.ASSISTANT if i % 2 else MessageRole.USER, content=f'Turn {i}: another scene') for i in range(20)]
    current = Message(role=MessageRole.USER, content='I changed my mind about that earlier claim.')
    messages = provider._reply_messages(current_instruction=PracticeInstruction(prompt='Discuss'),
        material=LearningMaterial(title='Book', source_language='english', content='The end.'),
        message_history=[*history, current], user_message=current, corrections=[], target_language=LanguageEnum.ENGLISH)
    prompt = '\n'.join(message.content for message in messages)
    assert 'EARLY_STANCE' in prompt and prompt.count(current.content) == 1
    assert 'may since have changed' in prompt and 'Do not end every reply' in prompt


def test_section_length_failure_increases_budget_once_instead_of_identical_retry():
    class Client:
        calls = []
        async def ainvoke(self, messages, **kwargs):
            self.calls.append(kwargs)
            return AIMessage(content='truncated', response_metadata={'finish_reason': 'length'})
    async def run():
        client = Client()
        provider = OpenAICompatibleLLMProvider(OpenAICompatibleLLMSettings(api_key=SecretStr('test'),
            base_url='https://api.deepseek.com/v1', reasoning_model='deepseek-v4-pro'),
            reasoning_client=client, dialogue_client=client)
        with pytest.raises(ValueError, match='输出预算'):
            await provider.analyze_material_section(material=LearningMaterial(title='Book', source_language='english', content='A scene.'),
                target_language=LanguageEnum.ENGLISH, native_language=LanguageEnum.CHINESE)
        assert [call['max_tokens'] for call in client.calls] == [16000, 24000]
        assert all(call['reasoning_effort'] == 'low' for call in client.calls)
    asyncio.run(run())


def test_parallel_failure_cancels_running_section_tasks():
    class Fails(MockLearningLLMProvider):
        preparation_concurrency = 3
        active = 0
        async def analyze_material_section(self, **kwargs):
            self.active += 1
            try:
                if 'section 2/' in kwargs['material'].title:
                    await asyncio.sleep(0)
                    raise RuntimeError('transport')
                await asyncio.sleep(10)
            finally:
                self.active -= 1
    async def run():
        provider = Fails()
        material = LearningMaterial(title='Book', source_language='english', content='A chapter.\n' * 4000)
        with pytest.raises(RuntimeError): await prepare_material(provider, material, profile())
        assert provider.active == 0
    asyncio.run(run())


def test_empty_real_transport_response_does_not_save_a_blank_turn(tmp_path):
    from lingualoop.application import LearningWorkbench
    from lingualoop.infrastructure import SQLiteStore
    class Empty(MockLearningLLMProvider):
        async def stream_reply(self, **kwargs):
            yield '  '
    async def run():
        work = LearningWorkbench(Empty(), event_store=SQLiteStore(tmp_path / 'empty.sqlite3'))
        await work.load_material(title='Book', source_language=LanguageEnum.ENGLISH, target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE, learner_level='B2', content='Mira returned to the empty lighthouse.')
        await work.start_session()
        count = len(work.session.messages)
        with pytest.raises(ValueError, match='未返回文字'): await work.send_message('Why did she return?')
        assert len(work.session.messages) == count + 1
        assert work.session.messages[-1].content == 'Why did she return?'
        await work.aclose()
    asyncio.run(run())


def test_whole_book_length_failure_changes_budget_and_keeps_thinking_role():
    class Client:
        def __init__(self, valid): self.valid, self.calls = valid, []
        async def ainvoke(self, messages, **kwargs):
            self.calls.append(kwargs)
            return AIMessage(content='truncated', response_metadata={'finish_reason': 'length'}) if len(self.calls) == 1 else AIMessage(content=self.valid)
    async def run():
        material = LearningMaterial(title='Book', source_language='japanese', content='二人が駅へ行った。')
        section = await MockLearningLLMProvider().analyze_material(material=material,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        section.outline = ['opening', 'ending']
        client = Client(section.model_dump_json())
        provider = OpenAICompatibleLLMProvider(OpenAICompatibleLLMSettings(api_key=SecretStr('test'),
            base_url='https://api.deepseek.com/v1', reasoning_model='deepseek-v4-pro'), reasoning_client=client, dialogue_client=client)
        result = await provider.synthesize_material(material=material, sections=[section, section],
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert result.topics
        assert [call['max_tokens'] for call in client.calls] == [24000, 32000]
        assert all(call['reasoning_effort'] == 'low' for call in client.calls)
    asyncio.run(run())


def test_retry_keeps_unvisited_cached_tail_when_first_missing_section_fails():
    class Fails(MockLearningLLMProvider):
        async def analyze_material(self, **kwargs): raise RuntimeError('network')
    async def run():
        material = LearningMaterial(title='Book', source_language='japanese', content='章の出来事。\n' * 5000)
        initial = await prepare_material(MockLearningLLMProvider(), material, profile())
        tail = initial.chunks[1:]
        material.analysis = initial.model_copy(update={'chunks': tail, 'preparation_complete': False})
        saved = []
        async def persist(analysis): saved.append(analysis)
        with pytest.raises(RuntimeError): await prepare_material(Fails(), material, profile(), persist)
        assert saved and [c.id for c in saved[-1].chunks] == [c.id for c in tail]
    asyncio.run(run())
