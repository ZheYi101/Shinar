"""Independent acceptance checks for routes, recovery and benchmark hygiene."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from lingualoop.application import LearningWorkbench
from lingualoop.core import FeedbackTiming, LanguageEnum, PracticeOptions, ProficiencyLevel
from lingualoop.core import AnswerBranch, DiscussionTopic, MaterialAnalysis
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers.mock import LegacyMockLearningLLMProvider
from lingualoop.providers.openai_compatible import OpenAICompatibleLLMProvider, OpenAICompatibleLLMSettings
from langchain_core.messages import AIMessage
from pydantic import SecretStr


def test_new_discussion_routes_only_dialogue_despite_legacy_feedback_and_failed_background(tmp_path):
    class AuditProvider(LegacyMockLearningLLMProvider):
        def __init__(self):
            self.calls = []
            self.fail_next_stream = True

        async def prepare_dialogue(self, **kwargs):
            self.calls.append("background_reasoning")
            await asyncio.sleep(0)
            raise RuntimeError("Reasoning provider unavailable")

        async def correct_answer(self, **kwargs):
            self.calls.append("foreground_correction")
            raise AssertionError("New discussion must not call reasoning correction")

        async def summarize_session(self, **kwargs):
            self.calls.append("end_summary")
            # The mock summary internally computes end-only corrections; that is allowed.
            return await LegacyMockLearningLLMProvider().summarize_session(**kwargs)

        async def stream_reply(self, **kwargs):
            self.calls.append("dialogue")
            if self.fail_next_stream:
                self.fail_next_stream = False
                yield "未完了"
                raise RuntimeError("Stream disconnected")
            yield "そうですね。"
            await asyncio.sleep(0)
            yield "どう思いますか。"

    async def scenario():
        provider = AuditProvider()
        database = tmp_path / "acceptance.sqlite3"
        work = LearningWorkbench(provider, event_store=SQLiteStore(database))
        await work.load_material(title="公園の散歩", source_language=LanguageEnum.JAPANESE,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1, content="花子は公園で太郎に会った。二人は雨の話をした。")
        await work.start_session(topic_id=work.material.analysis.topics[0].id,
                                 options=PracticeOptions(feedback_timing=FeedbackTiming.IMMEDIATE))
        await asyncio.sleep(0.02)
        assert work.preparation_status == "unavailable"
        with pytest.raises(RuntimeError, match="Stream disconnected"):
            await work.send_message("雨は好きです。")
        assert len(work.session.messages) == 2
        confirmed_id = work.session.messages[-1].id
        deltas = []
        result = await work.send_message("雨は好きです。", on_delta=deltas.append)
        assert result.session.messages[-2].id == confirmed_id
        assert result.assistant_message.content == "".join(deltas)
        assert result.feedback_items == []
        assert "foreground_correction" not in provider.calls
        await asyncio.sleep(0.02)
        assert work.preparation_status == "unavailable"
        await work.complete_session()
        expected_id = work.session.id
        await work.aclose()
        assert not work._preparation_tasks
        restored = LearningWorkbench(provider, event_store=SQLiteStore(database))
        assert restored.session.id == expected_id
        assert restored.session.status.value == "completed"
        assert len(restored.session.messages) == 3
        assert all("未完了" not in message.content for message in restored.session.messages)
        await restored.aclose()

    asyncio.run(scenario())


def test_benchmark_import_does_not_load_credentials_and_source_ruby_is_not_duplicated(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spec = importlib.util.spec_from_file_location("acceptance_probe", Path(__file__).parents[1] / "scripts/benchmark_prepared_dialogue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import os
    assert os.environ.get("OPENAI_API_KEY") is None
    sample = '<h1>not body</h1><div class="main_text">糸<ruby>犍陀多<rp>（</rp><rt>かんだた</rt><rp>）</rp></ruby><br>終わり。</div><div>not body</div>'
    assert module.source_text(sample) == "糸犍陀多\n終わり。"


def test_long_material_topic_budget_retains_every_chapter_including_last(tmp_path):
    """Nine complete chunks overflow the 60-topic display budget; no late chapter disappears."""
    markers = [f"第{index+1}章では、人物{index+1}が町{index+1}へ向かった。" for index in range(8)]
    markers.append("最終章では、森に銀の時計を残した。")
    text = "".join(marker + "あ" * (12000-len(marker)-1) + "。" for marker in markers)

    class ChapterProvider(LegacyMockLearningLLMProvider):
        async def analyze_material(self, *, material, **kwargs):
            marker = material.content.split("。", 1)[0] + "。"
            branch = AnswerBranch(user_intent="気になる", response_points=[marker], suggested_reply="気になりますね。",
                follow_up="どう思いますか。", source_excerpts=[marker])
            return MaterialAnalysis(summary=marker, outline=[marker], topics=[DiscussionTopic(
                title=f"{marker}の話題{index+1}", opening_question="どう思いますか。",
                source_excerpt=marker, answer_branches=[branch]) for index in range(8)])

    async def scenario():
        work = LearningWorkbench(ChapterProvider(), event_store=SQLiteStore(tmp_path / "chapters.sqlite3"))
        await work.load_material(title="九章の長い材料", source_language=LanguageEnum.JAPANESE,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1, content=text)
        analysis = work.material.analysis
        assert len(analysis.chunks) == 9
        assert len(analysis.topics) <= 60
        represented = {topic.source_excerpt for topic in analysis.topics}
        assert set(markers) <= represented
        assert analysis.chunks[-1].end_char == len(text)
        await work.aclose()

    asyncio.run(scenario())


def test_custom_topic_can_reach_detail_in_last_raw_chunk_beyond_summary(tmp_path):
    detail = "最後に、泉のそばで紫の鍵を見つけた。"
    opening = "最終章では二人が別れた。"
    text = "初めの章は旅の話。" + "あ" * 24000 + opening + "い" * 6000 + detail + "う" * 2000

    class CaptureClient:
        def __init__(self):
            self.prompts = []

        async def ainvoke(self, messages, **kwargs):
            self.prompts.append("\n".join(message.content for message in messages))
            return AIMessage(content=json.dumps({"title": "紫の鍵", "opening_question": "紫の鍵は気になりましたか。",
                "source_excerpt": detail, "answer_branches": [{"user_intent": "気になる", "response_points": [detail],
                "suggested_reply": "気になりますね。", "follow_up": "どう思いますか。", "source_excerpts": [detail]}]}, ensure_ascii=False))

    async def scenario():
        # Prepared summaries deliberately omit the key. Retrieval must consult source chunks.
        from lingualoop.core import LearningMaterial, PreparedChunk
        fixture = LearningMaterial(title="旅の九章", source_language=LanguageEnum.JAPANESE, content=text,
            analysis=MaterialAnalysis(summary="二人は旅をした。", outline=["二人は旅をした。"],
                topics=[DiscussionTopic(title="別れ", opening_question="どう思いますか。", source_excerpt=opening)],
                chunks=[PreparedChunk(start_char=0, end_char=24000, summary="旅の始まり", source_excerpt=text[:200]),
                    PreparedChunk(start_char=24000, end_char=len(text), summary="旅の終わり", source_excerpt=opening)]))
        client = CaptureClient()
        provider = OpenAICompatibleLLMProvider(OpenAICompatibleLLMSettings(api_key=SecretStr("unit-test-only"),
            base_url="https://example.test/v1", reasoning_model="pro"), reasoning_client=client, dialogue_client=client)
        topic = await provider.prepare_custom_topic(material=fixture, title="最終章の泉で見つけた紫の鍵について",
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert topic.source_excerpt == detail
        assert detail in client.prompts[0]
        assert len(client.prompts[0]) < 16000
        await provider.aclose()

    asyncio.run(scenario())


def test_last_background_probe_blocks_second_paid_call_and_keeps_safe_finish_reason():
    spec = importlib.util.spec_from_file_location("acceptance_budget_probe", Path(__file__).parents[1] / "scripts/benchmark_prepared_dialogue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Client:
        model_name = "pro"
        max_tokens = 2500
        reasoning_effort = "low"
        def __init__(self): self.calls = 0
        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            return AIMessage(content="{}", response_metadata={"finish_reason": "length"})

    async def scenario():
        client, records = Client(), []
        audited = module.AuditClient(client, "reasoning", records, max_calls=1)
        await audited.ainvoke([])
        with pytest.raises(RuntimeError, match="budget reached"):
            await audited.ainvoke([])
        assert client.calls == 1 and len(records) == 1
        assert records[0]["finish_reason"] == "length"
        assert "content" not in records[0]

    asyncio.run(scenario())
