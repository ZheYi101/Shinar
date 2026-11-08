from __future__ import annotations

import asyncio
import json
import zipfile
from time import perf_counter

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import SecretStr

from shinar.application import LearningWorkbench
from shinar.application.material_preparation import split_material
from shinar.core import (
    DialoguePreparation, LanguageEnum, LearningMaterial, Message, MessageRole,
    PracticeInstruction, ProficiencyLevel,
)
from shinar.infrastructure import SQLiteStore
from shinar.infrastructure.material_import import import_material_file
from shinar.providers.mock import LegacyMockLearningLLMProvider
from shinar.providers.openai_compatible import OpenAICompatibleLLMProvider, OpenAICompatibleLLMSettings


async def load(work, text="太郎は駅で友達の花子に会った。二人は旅行の予定を話した。"):
    return await work.load_material(title="旅行", source_language=LanguageEnum.JAPANESE,
        target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
        learner_level=ProficiencyLevel.B1, content=text)


def test_chunks_cover_whole_source_without_loss_and_budget_is_explicit(monkeypatch):
    text = ("第一章。\n" * 5000) + "最後の文。"
    chunks = list(split_material(text))
    assert "".join(part for _, _, part in chunks) == text
    assert all(text[start:end] == content and len(content) <= 12000 for start, end, content in chunks)
    monkeypatch.setenv("SHINAR_MAX_MATERIAL_CHARS", "12000")
    with pytest.raises(ValueError, match="材料已保存"):
        list(split_material(text))


def test_long_material_saves_progress_and_resumes_from_completed_chunks(tmp_path):
    class FailsSecondChunk(LegacyMockLearningLLMProvider):
        def __init__(self): self.calls = 0
        async def analyze_material(self, **kwargs):
            self.calls += 1
            if self.calls == 2: raise RuntimeError("transient")
            return await super().analyze_material(**kwargs)

    async def run():
        provider = FailsSecondChunk()
        store = SQLiteStore(tmp_path / "resume.sqlite3")
        work = LearningWorkbench(provider, event_store=store)
        text = "第一章。\n" * 5000
        with pytest.raises(RuntimeError): await load(work, text)
        assert len(work.material.analysis.chunks) == 1
        assert work.material.analysis.preparation_complete is False
        restored = LearningWorkbench(provider, event_store=store)
        await restored.analyze_current_material()
        assert provider.calls == 4  # first saved + failed second + retry second + third
        assert restored.material.analysis.preparation_complete
        chunks = restored.material.analysis.chunks
        assert chunks[0].start_char == 0 and chunks[-1].end_char == len(restored.material.content)
        assert all(topic.source_excerpt in text for topic in restored.material.analysis.topics)
        assert all(branch.source_excerpts for topic in restored.material.analysis.topics for branch in topic.answer_branches)
        await restored.aclose()
    asyncio.run(run())


def test_custom_topic_is_prepared_and_persisted_before_conversation(tmp_path):
    async def run():
        store = SQLiteStore(tmp_path / "custom.sqlite3")
        work = LearningWorkbench(LegacyMockLearningLLMProvider(), event_store=store)
        await load(work)
        started = await work.start_session(custom_topic="人物的友谊")
        topic = started.session.topic
        assert topic.category == "custom" and topic.answer_branches
        assert store.get_material(work.material.id).analysis.topics[-1].id == topic.id
        assert topic.opening_question != topic.title
        await work.aclose()
    asyncio.run(run())


def test_foreground_stream_does_not_wait_for_reasoning_and_measures_both_times(tmp_path):
    class BlockedReasoning(LegacyMockLearningLLMProvider):
        async def prepare_dialogue(self, **kwargs):
            await asyncio.Future()
        async def stream_reply(self, **kwargs):
            await asyncio.sleep(0.01)
            yield "そうですね。"
            await asyncio.sleep(0.025)
            yield "なぜですか？"
        async def correct_answer(self, **kwargs):
            raise AssertionError("Foreground reasoning is forbidden")
    async def run():
        work = LearningWorkbench(BlockedReasoning(), event_store=SQLiteStore(tmp_path / "stream.sqlite3"))
        await load(work)
        await work.start_session(topic_id=work.material.analysis.topics[0].id)
        await asyncio.sleep(0)
        assert work.preparation_status == "preparing"
        deltas = []
        result = await asyncio.wait_for(work.send_message("友達が好きです。", on_delta=deltas.append), timeout=1)
        assert "".join(deltas) == result.assistant_message.content
        assert 0 < result.timing.ttft_ms < result.timing.total_ms
        assert result.timing.streamed
        assert result.assistant_message.metadata["timing"]["total_ms"] == result.timing.total_ms
        assert len(work.session.messages) == 3
        await work.aclose()
        assert not work._preparation_tasks
    asyncio.run(run())


def test_stale_prediction_is_discarded_even_if_provider_ignores_cancellation(tmp_path):
    class LatePrediction(LegacyMockLearningLLMProvider):
        def __init__(self): self.started = asyncio.Event(); self.calls = 0
        async def prepare_dialogue(self, *, material, session):
            self.calls += 1
            self.started.set()
            try:
                await asyncio.sleep(0.03)
            except asyncio.CancelledError:
                pass
            return DialoguePreparation(based_on_message_count=len(session.messages),
                predicted_intents=[f"revision {len(session.messages)}"],
                response_points=["candidate only"], source_excerpts=[material.content[:10]])
    async def run():
        provider = LatePrediction()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "stale.sqlite3"))
        await load(work)
        await work.start_session(topic_id=work.material.analysis.topics[0].id)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        await work.send_message("違うと思います。")
        await asyncio.sleep(0.07)
        assert work.session.preparation.based_on_message_count == 3
        assert "revision 1" not in json.dumps(work.session.model_dump(mode="json"))
        assert all("candidate only" not in item.content for item in work.session.messages)
        work.reset()
        await asyncio.sleep(0)
        assert work.session is None and work.preparation_status == "idle"
        await work.aclose()
    asyncio.run(run())


def test_duplicate_send_and_failed_stream_do_not_save_partial_messages(tmp_path):
    class FailingStream(LegacyMockLearningLLMProvider):
        def __init__(self): self.started = asyncio.Event(); self.resume = asyncio.Event()
        async def stream_reply(self, **kwargs):
            yield "partial"
            self.started.set()
            await self.resume.wait()
            raise RuntimeError("network interrupted")
    async def run():
        provider = FailingStream()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "failure.sqlite3"))
        await load(work)
        await work.start_session()
        first = asyncio.create_task(work.send_message("こんにちは"))
        await provider.started.wait()
        with pytest.raises(RuntimeError, match="上一条"):
            await work.send_message("duplicate")
        provider.resume.set()
        with pytest.raises(RuntimeError): await first
        assert len(work.session.messages) == 2
        assert work.session.messages[-1].content == "こんにちは"
        assert all(message.content != "partial" for message in work.session.messages)
        assert work._sending is False
        await work.aclose()
    asyncio.run(run())


def test_deepseek_role_settings_do_not_apply_legacy_disable_to_reasoning(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("OPENAI_REASONING_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("OPENAI_DIALOGUE_MODEL", "deepseek-flash")
    monkeypatch.setenv("OPENAI_DISABLE_THINKING", "1")
    settings = OpenAICompatibleLLMSettings.from_env()
    reasoning, dialogue = settings.reasoning_client_kwargs(), settings.dialogue_client_kwargs()
    assert reasoning["extra_body"] == {"thinking": {"type": "enabled"}}
    assert reasoning["reasoning_effort"] == "high"
    assert dialogue["extra_body"] == {"thinking": {"type": "disabled"}}
    assert dialogue["max_tokens"] <= 160


def test_restored_legacy_session_does_not_put_reasoning_back_in_foreground(tmp_path):
    class NoForegroundReasoning(LegacyMockLearningLLMProvider):
        async def correct_answer(self, **kwargs):
            raise AssertionError("Legacy restore must not call reasoning correction")
    async def run():
        store = SQLiteStore(tmp_path / "legacy.sqlite3")
        work = LearningWorkbench(LegacyMockLearningLLMProvider(), event_store=store)
        await load(work)
        await work.start_session()
        old = work.session.model_copy(update={"options": None})
        history = [message.model_dump() for message in old.messages]
        store.save_session(old)
        await work.aclose()
        restored = LearningWorkbench(NoForegroundReasoning(), event_store=store)
        assert restored.session.options is not None
        assert [message.model_dump() for message in restored.session.messages] == history
        result = await restored.send_message("友達が大切だと思います。")
        assert result.assistant_message and result.feedback_items == []
        await restored.aclose()
    asyncio.run(run())


def test_dialogue_prompt_uses_bounded_preparation_and_ignores_reasoning_content():
    class Streaming:
        def __init__(self): self.calls = []
        async def astream(self, messages):
            self.calls.append(messages)
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "private reasoning"})
            yield AIMessageChunk(content="こんにちは。")
    async def run():
        client = Streaming()
        settings = OpenAICompatibleLLMSettings(api_key=SecretStr("test"), base_url="https://example.test/v1", reasoning_model="pro")
        provider = OpenAICompatibleLLMProvider(settings, reasoning_client=client, dialogue_client=client)
        material = LearningMaterial(title="Book", source_language=LanguageEnum.JAPANESE, content="A" * 100000 + "DO_NOT_COPY_THE_END")
        parts = [part async for part in provider.stream_reply(current_instruction=PracticeInstruction(prompt="話しましょう"),
            material=material, message_history=[], user_message=Message(role=MessageRole.USER, content="好きです"), corrections=[], target_language=LanguageEnum.JAPANESE)]
        assert "".join(parts) == "こんにちは。"
        prompt = "\n".join(message.content for message in client.calls[0])
        assert len(prompt) < 10000 and "DO_NOT_COPY_THE_END" not in prompt
        assert "hypothetical" in prompt and "untrusted data" in prompt
    asyncio.run(run())


def test_dialogue_packet_deduplicates_evidence_and_current_user_without_changing_output_budget():
    from shinar.providers.openai_compatible import _compact_reply_packet
    quote = "二人は旅行について話した。"
    branches = [{"user_intent": "旅行が好き", "response_points": ["二人が旅行の話をした"],
        "suggested_reply": "いいですね。", "follow_up": "どこに行きたいですか？", "source_excerpts": [quote]}] * 3
    material = LearningMaterial(title="旅", source_language=LanguageEnum.JAPANESE, content=quote)
    topic = {"title": "旅行", "opening_question": "旅行は好きですか？", "source_excerpt": quote, "answer_branches": branches}
    packet = _compact_reply_packet(material, topic, None)
    assert packet["evidence"] == [quote]
    assert all(branch["evidence_ids"] == [0] for branch in packet["branches"])
    settings = OpenAICompatibleLLMSettings(api_key=SecretStr("test"), base_url="https://example.test/v1", reasoning_model="pro")
    client = object()
    actual = OpenAICompatibleLLMProvider(settings, reasoning_client=client, dialogue_client=client)
    current = Message(role=MessageRole.USER, content="UNIQUE_CURRENT_ANSWER")
    prompt = actual._reply_messages(current_instruction=PracticeInstruction(prompt="duplicate opening", metadata={"topic": topic}),
        material=material, message_history=[current], user_message=current, corrections=[], target_language=LanguageEnum.JAPANESE)
    text = "\n".join(item.content for item in prompt)
    assert text.count("UNIQUE_CURRENT_ANSWER") == 1
    assert text.count(quote) == 1
    assert settings.dialogue_client_kwargs()["max_tokens"] == 160


def test_epub_import_preserves_spine_order_and_drops_ruby_readings(tmp_path):
    path = tmp_path / "novel.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        archive.writestr("OPS/book.opf", '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>真实书名</dc:title></metadata><manifest><item id="second" href="b.xhtml"/><item id="first" href="a.xhtml"/></manifest><spine><itemref idref="first"/><itemref idref="second"/></spine></package>')
        archive.writestr("OPS/a.xhtml", '<h1>第一章</h1><p><ruby>旅<rt>たび</rt></ruby>に出た。</p><script>untrusted()</script>')
        archive.writestr("OPS/b.xhtml", '<h1>第二章</h1><p>帰った。</p>')
    imported = import_material_file(path)
    assert imported.title == '真实书名'
    assert imported.normalized_content.index("第一章") < imported.normalized_content.index("第二章")
    assert "旅に出た。" in imported.normalized_content
    assert "たび" not in imported.normalized_content and "untrusted" not in imported.normalized_content


def test_xlsx_import_reads_all_sheets_and_video_uses_subtitle_only(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "novel.xlsx"
    book = Workbook()
    book.active.title = "第一章"
    book.active.append(["太郎", "駅へ行った。"])
    book.create_sheet("第二章").append(["花子", "一緒に旅をした。"])
    book.save(path)
    imported = import_material_file(path)
    assert "第一章" in imported.normalized_content and "第二章" in imported.normalized_content
    assert "太郎 | 駅へ行った。" in imported.normalized_content
    video = tmp_path / "episode.mkv"
    video.write_bytes(b"video placeholder")
    with pytest.raises(ValueError, match="同名"):
        import_material_file(video)
    video.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕だけ。\n", encoding="utf-8")
    subtitles = import_material_file(video)
    assert subtitles.normalized_content == "字幕だけ。"
    assert "frames were not analyzed" in subtitles.diagnostics[-1]


def test_eight_section_book_balances_topic_budget_and_custom_topic_retrieves_tail():
    from shinar.application.material_preparation import _merge_analyses
    from shinar.core import MaterialAnalysis, PreparedChunk, DiscussionTopic, AnswerBranch
    from shinar.core.material_context import custom_topic_context
    analyses, chunks, source_parts = [], [], []
    offset = 0
    for index in range(8):
        keyword = "星祭りの約束" if index == 7 else f"chapter{index} の出来事"
        source = f"第{index+1}章。{keyword}を二人で話した。"
        source_parts.append(source)
        topics = [DiscussionTopic(title=f"{index+1}章の話題{number}", opening_question="どう思いますか？", source_excerpt=source,
            answer_branches=[AnswerBranch(user_intent="興味がある", response_points=[keyword], suggested_reply="面白いですね。",
                follow_up="どこが気になりますか？", source_excerpts=[source])]) for number in range(10)]
        analysis = MaterialAnalysis(summary=source, outline=[source], topics=topics)
        analyses.append(analysis)
        chunks.append(PreparedChunk(id=f"section-{index+1}", start_char=offset, end_char=offset+len(source),
            summary=source, source_excerpt=source, analysis_payload=analysis.model_dump(mode="json")))
        offset += len(source)
    material = LearningMaterial(title="八章の小説", source_language=LanguageEnum.JAPANESE, content="".join(source_parts))
    material.analysis = _merge_analyses(analyses, chunks, material, complete=True)
    assert len(material.analysis.topics) == 60
    for index in range(8):
        assert any(f"section-{index+1}" in topic.source_chunk_ids for topic in material.analysis.topics)
    context = custom_topic_context(material, "星祭りの約束について")
    assert "section-8" in context["coverage"]["selected_chunk_ids"]
    assert any("星祭り" in quote for quote in context["evidence"])
    assert len(context["whole_material_overview"]) == 8
    assert context["coverage"]["total_chunks"] == 8


def test_material_wall_budget_keeps_completed_chunks_and_retry_resumes(tmp_path, monkeypatch):
    class SlowSecond(LegacyMockLearningLLMProvider):
        def __init__(self): self.calls = 0
        async def analyze_material(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                await asyncio.sleep(2)
            return await super().analyze_material(**kwargs)
    async def run():
        monkeypatch.setenv("SHINAR_PREPARATION_DEADLINE_SECONDS", "1")
        provider = SlowSecond()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "deadline.sqlite3"))
        with pytest.raises(ValueError, match="本次材料整理达到 1 秒"):
            await load(work, "第一章。\n" * 5000)
        assert len(work.material.analysis.chunks) == 1
        assert not work.material.analysis.preparation_complete
        await work.analyze_current_material()
        assert provider.calls == 4 and work.material.analysis.preparation_complete
        await work.aclose()
    asyncio.run(run())
