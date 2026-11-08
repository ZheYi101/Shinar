import asyncio

from langchain_core.messages import AIMessage
from pydantic import SecretStr

from shinar.core.domain import (
    LanguageEnum,
    LearningMaterial,
    Message,
    MessageRole,
    PracticeInstruction,
)
from shinar.core.knowledge import ReasoningRequest, TurnContext, TurnEvidence, model_call_usage
from shinar.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
    OpenAICompatibleLLMSettings,
)


class Client:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return AIMessage(
            content='{"notes":[]}',
            usage_metadata={"input_tokens": 120, "output_tokens": 200, "total_tokens": 320},
            response_metadata={"finish_reason": "stop"},
        )


def test_new_reasoning_tasks_route_to_reasoning_with_request_budgets():
    async def run():
        reasoning, dialogue = Client(), Client()
        provider = OpenAICompatibleLLMProvider(
            OpenAICompatibleLLMSettings(
                api_key=SecretStr("fake"),
                base_url="https://api.deepseek.com/v1",
                reasoning_model="configured-thinker",
                dialogue_model="configured-chat",
            ),
            reasoning_client=reasoning,
            dialogue_client=dialogue,
        )
        for method in (
            provider.prepare_source_unit,
            provider.summarize_reading,
            provider.prepare_focus,
            provider.summarize_conversation,
        ):
            observed = {}
            token = model_call_usage.set(observed)
            try:
                result = await method(
                    ReasoningRequest(payload={"source": "quoted data"}, max_tokens=2048)
                )
                assert result.usage["input_tokens"] == 120
                assert observed["output_tokens"] == 200
            finally:
                model_call_usage.reset(token)
        assert len(reasoning.calls) == 4 and not dialogue.calls
        assert all(
            options == {"max_tokens": 2048, "reasoning_effort": "low"}
            for _, options in reasoning.calls
        )
        await provider.aclose()

    asyncio.run(run())


def test_local_turn_context_is_consumed_without_a_second_provider_retrieval():
    async def run():
        reasoning, dialogue = Client(), Client()
        provider = OpenAICompatibleLLMProvider(
            OpenAICompatibleLLMSettings(
                api_key=SecretStr("fake"),
                base_url="https://example.test/v1",
                reasoning_model="r",
                dialogue_model="d",
            ),
            reasoning_client=reasoning,
            dialogue_client=dialogue,
        )
        material = LearningMaterial(
            title="River", content="UNSELECTED FULL SOURCE", source_language=LanguageEnum.ENGLISH
        )
        context = TurnContext(
            title="River",
            scope_end=10,
            source_hash="hash",
            brief="Allowed overview",
            evidence=[TurnEvidence(id="p1", text="Ren hesitated.", start_char=0, end_char=14)],
        )
        message = Message(role=MessageRole.USER, content="I changed my mind about Ren.")
        await provider.generate_reply(
            current_instruction=PracticeInstruction(
                prompt="free chat", metadata={"turn_context": context.model_dump(mode="json")}
            ),
            material=material,
            message_history=[message],
            user_message=message,
            corrections=[],
            target_language=LanguageEnum.ENGLISH,
        )
        assert not reasoning.calls and len(dialogue.calls) == 1
        packet = " ".join(str(item.content) for item in dialogue.calls[0][0])
        assert packet.count(message.content) == 1
        assert "UNSELECTED FULL SOURCE" not in packet
        assert "Allowed overview" in packet and "Ren hesitated." in packet
        await provider.aclose()

    asyncio.run(run())
