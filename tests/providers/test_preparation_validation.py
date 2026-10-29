"""Regression evidence for independent audit A1/A2. All clients are offline."""
from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from lingualoop.application import LearningWorkbench
from lingualoop.core import (
    DialoguePreparation, DiscussionTopic, LanguageEnum, LearningMaterial,
    PracticeSession, ProficiencyLevel, SessionUserProfile,
)
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider
from lingualoop.providers.openai_compatible import OpenAICompatibleLLMProvider, OpenAICompatibleLLMSettings

SOURCE = "太郎は駅で花子に会った。二人は旅行について話した。"


class Replies:
    def __init__(self, *payloads):
        self.payloads = iter(payloads)
        self.calls = []
    async def ainvoke(self, messages, **kwargs):
        self.calls.append(messages)
        return AIMessage(content=json.dumps(next(self.payloads), ensure_ascii=False))


def provider(client):
    settings = OpenAICompatibleLLMSettings(api_key=SecretStr("unit-test"),
        base_url="https://example.invalid/v1", reasoning_model="reasoning", dialogue_model="dialogue")
    return OpenAICompatibleLLMProvider(settings, reasoning_client=client, dialogue_client=client)


def material():
    return LearningMaterial(title="旅", source_language=LanguageEnum.JAPANESE, content=SOURCE)


def session():
    return PracticeSession(material_id="test", pattern_id="discussion", profile=SessionUserProfile(
        profile_level=ProficiencyLevel.B1, native_language=LanguageEnum.CHINESE, target_language=LanguageEnum.JAPANESE))


def valid_preparation():
    return {"predicted_intents": ["旅行が好き"], "response_points": ["二人が旅行の話をした"],
        "source_excerpts": ["二人は旅行について話した。"]}


def valid_branch():
    return {"user_intent": "旅行が好き", "response_points": ["二人は旅行の話をした"],
        "suggested_reply": "旅行の話は楽しいですね。", "follow_up": "どこへ行きたいですか？",
        "source_excerpts": ["二人は旅行について話した。"]}


def topic_payload(**updates):
    return {"title": "旅行", "opening_question": "旅行は好きですか？", "source_excerpt": SOURCE,
        "answer_branches": [valid_branch()], **updates}


@pytest.mark.parametrize("missing", ["predicted_intents", "response_points", "source_excerpts"])
@pytest.mark.parametrize("shape", ["missing", "empty", "blank"])
def test_background_missing_empty_or_blank_fields_retry_then_fail(missing, shape):
    invalid = valid_preparation()
    if shape == "missing": invalid.pop(missing)
    else: invalid[missing] = [] if shape == "empty" else [" "]
    async def run():
        client = Replies(invalid, invalid)
        with pytest.raises(ValueError, match="后台准备"):
            await provider(client).prepare_dialogue(material=material(), session=session())
        assert len(client.calls) == 2
    asyncio.run(run())


def test_background_partial_invalid_quotations_reject_then_valid_retry_succeeds():
    invalid = {**valid_preparation(), "source_excerpts": [SOURCE, "材料外事实"]}
    async def run():
        client = Replies(invalid, valid_preparation())
        result = await provider(client).prepare_dialogue(material=material(), session=session())
        assert result.source_excerpts == ["二人は旅行について話した。"]
        assert len(client.calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize("branches", [None, [], [{"user_intent": "喜欢"}],
    [{**valid_branch(), "source_excerpts": []}], [{**valid_branch(), "source_excerpts": ["不存在"]}]])
def test_custom_topic_requires_valid_nonempty_branch_and_retries(branches):
    invalid = topic_payload(answer_branches=branches)
    if branches is None: invalid.pop("answer_branches")
    async def run():
        client = Replies(invalid, invalid)
        with pytest.raises(ValueError, match="自定话题"):
            await provider(client).prepare_custom_topic(material=material(), title="自定题",
                target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert len(client.calls) == 2
    asyncio.run(run())


def test_custom_topic_keeps_valid_branch_and_drops_partial_invalid_branch():
    async def run():
        payload = topic_payload(answer_branches=[{**valid_branch(), "source_excerpts": ["不存在"]}, valid_branch()])
        client = Replies(payload)
        result = await provider(client).prepare_custom_topic(material=material(), title="自定题",
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert len(result.answer_branches) == 1 and len(client.calls) == 1
        assert result.title == "自定题"
    asyncio.run(run())


def test_custom_topic_bad_shape_then_valid_retry_succeeds():
    async def run():
        client = Replies(topic_payload(answer_branches=[]), topic_payload())
        result = await provider(client).prepare_custom_topic(material=material(), title="自定题",
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert result.answer_branches and len(client.calls) == 2
    asyncio.run(run())


def test_material_new_topics_use_same_strict_branch_gate():
    async def run():
        client = Replies({"summary": "旅行", "topics": [topic_payload(answer_branches=[])]},
                         {"summary": "旅行", "topics": [topic_payload()]})
        result = await provider(client).analyze_material(material=material(),
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE)
        assert result.topics[0].answer_branches and len(client.calls) == 2
    asyncio.run(run())


def test_workbench_rejects_invalid_adapter_preparation_and_preserves_old_valid_snapshot(tmp_path):
    class FailsAfterValid(MockLearningLLMProvider):
        def __init__(self): self.calls = 0
        async def prepare_dialogue(self, *, material, session):
            self.calls += 1
            if self.calls == 1:
                return await super().prepare_dialogue(material=material, session=session)
            return DialoguePreparation(based_on_message_count=len(session.messages),
                predicted_intents=["new possibility"], response_points=["unsupported claim"])
    async def run():
        store = SQLiteStore(tmp_path / "guard.sqlite3")
        work = LearningWorkbench(FailsAfterValid(), event_store=store)
        await work.load_material(title="旅", source_language=LanguageEnum.JAPANESE,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1, content=SOURCE)
        await work.start_session(topic_id=work.material.analysis.topics[0].id)
        await asyncio.gather(*work._preparation_tasks)
        old = work.session.preparation.model_dump()
        assert work.preparation_status == "ready"
        result = await work.send_message("旅行が好きです。")
        await asyncio.gather(*work._preparation_tasks)
        assert result.assistant_message
        assert work.preparation_status == "unavailable"
        assert work.session.preparation.model_dump() == old
        assert store.list_sessions()[0].preparation.model_dump() == old
        assert all("unsupported claim" not in message.content for message in work.session.messages)
        await work.aclose()
    asyncio.run(run())


def test_legacy_payloads_still_read_empty_preparation_fields():
    assert DialoguePreparation(based_on_message_count=1).source_excerpts == []
    assert DiscussionTopic(title="legacy", opening_question="question", source_excerpt=SOURCE).answer_branches == []


def test_legacy_unverified_snapshot_is_not_consumed_by_dialogue_model(tmp_path):
    class Capture(MockLearningLLMProvider):
        async def generate_reply(self, *, current_instruction, **kwargs):
            self.metadata = current_instruction.metadata
            return await super().generate_reply(current_instruction=current_instruction, **kwargs)
    async def run():
        store = SQLiteStore(tmp_path / "old-prepare.sqlite3")
        work = LearningWorkbench(MockLearningLLMProvider(), event_store=store)
        await work.load_material(title="旅", source_language=LanguageEnum.JAPANESE,
            target_language=LanguageEnum.JAPANESE, native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1, content=SOURCE)
        await work.start_session()
        await work.aclose()
        old = work.session.model_copy(update={"preparation": DialoguePreparation(
            based_on_message_count=len(work.session.messages), predicted_intents=["synthetic"],
            response_points=["old uncited claim"])})
        store.save_session(old)
        capture = Capture()
        restored = LearningWorkbench(capture, event_store=store)
        assert restored.session.preparation.response_points == ["old uncited claim"]  # readable history
        await restored.send_message("話しましょう。")
        assert "preparation" not in capture.metadata
        await restored.aclose()
    asyncio.run(run())


def test_deepseek_background_uses_low_effort_bounded_output_without_changing_analysis():
    class CaptureOptions(Replies):
        async def ainvoke(self, messages, **kwargs):
            self.options = kwargs
            return await super().ainvoke(messages, **kwargs)
    async def run():
        settings = OpenAICompatibleLLMSettings(api_key=SecretStr("unit-test"), base_url="https://api.deepseek.com/v1",
            reasoning_model="deepseek-v4-pro", dialogue_model="deepseek-flash")
        client = CaptureOptions(valid_preparation())
        actual = OpenAICompatibleLLMProvider(settings, reasoning_client=client, dialogue_client=client)
        await actual.prepare_dialogue(material=material(), session=session())
        assert client.options == {"reasoning_effort": "low", "max_tokens": 4000}
        assert settings.reasoning_client_kwargs()["reasoning_effort"] == "high"
        assert settings.reasoning_client_kwargs()["extra_body"] == {"thinking": {"type": "enabled"}}
    asyncio.run(run())


def test_deepseek_wire_body_preserves_documented_max_tokens_and_per_call_low_override():
    import httpx
    from langchain_openai.chat_models.base import BaseChatOpenAI
    from langchain_core.messages import HumanMessage
    async def run():
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
                "model": "deepseek-v4-pro", "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            settings = OpenAICompatibleLLMSettings(api_key=SecretStr("test"), base_url="https://api.deepseek.com/v1",
                reasoning_model="deepseek-v4-pro", dialogue_model="deepseek-flash")
            pro = BaseChatOpenAI(**settings.reasoning_client_kwargs(), http_async_client=http)
            flash = BaseChatOpenAI(**settings.dialogue_client_kwargs(), http_async_client=http)
            await pro.ainvoke([HumanMessage(content="test")])
            await pro.ainvoke([HumanMessage(content="test")], reasoning_effort="low", max_tokens=4000)
            await flash.ainvoke([HumanMessage(content="test")])
        assert [body["max_tokens"] for body in requests] == [24000, 4000, 160]
        assert all("max_completion_tokens" not in body for body in requests)
        assert requests[0]["thinking"] == requests[1]["thinking"] == {"type": "enabled"}
        assert requests[0]["reasoning_effort"] == "high" and requests[1]["reasoning_effort"] == "low"
        assert requests[2]["thinking"] == {"type": "disabled"}
        production = OpenAICompatibleLLMProvider(settings)
        assert type(production._reasoning_client) is BaseChatOpenAI
        assert type(production._dialogue_client) is BaseChatOpenAI
        await production.aclose()
    asyncio.run(run())


def test_micro_preparation_maps_compact_json_and_exposes_only_safe_diagnostics():
    class CompactClient:
        async def ainvoke(self, messages, **kwargs):
            self.prompt = "\n".join(message.content for message in messages)
            return AIMessage(content=json.dumps({"intent": "旅行先を話す", "points": ["二人は旅行の予定を話した"],
                "quote": SOURCE}, ensure_ascii=False), response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 400, "output_tokens": 300, "total_tokens": 700})
    async def run():
        client = CompactClient()
        actual = provider(client)
        result = await actual.prepare_dialogue(material=material(), session=session())
        assert result.predicted_intents == ["旅行先を話す"] and result.source_excerpts == [SOURCE]
        assert len(client.prompt) < 2200
        records = actual.preparation_diagnostics
        assert records[0]["result"] == "validated" and records[0]["finish_reason"] == "stop"
        assert records[0]["output_tokens"] == 300
        assert SOURCE not in json.dumps(records, ensure_ascii=False)
        assert "旅行先を話す" not in json.dumps(records, ensure_ascii=False)
    asyncio.run(run())


def test_length_termination_is_reported_without_raw_output_or_identical_retry():
    class Truncated:
        def __init__(self): self.calls = 0
        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            return AIMessage(content="RAW_PRIVATE_CONTENT", additional_kwargs={"reasoning_content": "PRIVATE_COT"},
                response_metadata={"finish_reason": "length"},
                usage_metadata={"input_tokens": 400, "output_tokens": 4000, "total_tokens": 4400})
    async def run():
        client = Truncated()
        actual = provider(client)
        with pytest.raises(ValueError, match="达到输出预算"):
            await actual.prepare_dialogue(material=material(), session=session())
        assert client.calls == 1
        assert actual.preparation_diagnostics[0]["result"] == "output_budget_exhausted"
        assert actual.preparation_diagnostics[0]["finish_reason"] == "length"
        serialized = json.dumps(actual.preparation_diagnostics)
        assert "RAW_PRIVATE_CONTENT" not in serialized and "PRIVATE_COT" not in serialized
    asyncio.run(run())


def test_background_invalid_json_diagnostic_and_single_attempt_probe_budget():
    class NonJSON:
        def __init__(self): self.calls = 0
        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            return AIMessage(content="invalid private response", response_metadata={"finish_reason": "stop"})
    async def run():
        client = NonJSON()
        actual = provider(client)
        actual._settings.background_max_attempts = 1
        with pytest.raises(ValueError, match="后台准备格式"):
            await actual.prepare_dialogue(material=material(), session=session())
        assert client.calls == 1 and actual.preparation_diagnostics[0]["result"] == "invalid_structure_or_evidence"
        assert actual.preparation_diagnostics[0]["failure_stage"] == "json_parse"
        assert "invalid private response" not in json.dumps(actual.preparation_diagnostics)
    asyncio.run(run())
