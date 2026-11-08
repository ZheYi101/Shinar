import asyncio

from langchain_core.messages import AIMessage
from pydantic import SecretStr

from shinar.core import (
    FeedbackItem,
    LanguageEnum,
    LearningMaterial,
    MaterialAnalysis,
    MaterialExpression,
    Message,
    MessageRole,
    PracticeInstruction,
    PracticeSession,
    ProficiencyLevel,
    ReviewItemKind,
    SessionUserProfile,
)
from shinar.providers.openai_compatible import (
    OpenAICompatibleLLMProvider,
    OpenAICompatibleLLMSettings,
    normalize_openai_base_url,
)


class FakeChatClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.response)


def test_normalize_openai_base_url_adds_v1_only_for_root_url() -> None:
    assert normalize_openai_base_url("https://api.example.com") == (
        "https://api.example.com/v1"
    )
    assert normalize_openai_base_url("https://api.example.com/v1") == (
        "https://api.example.com/v1"
    )


def test_preparation_cache_identity_survives_key_rotation_but_separates_models():
    def identity(**changes):
        settings = _settings().model_copy(update=changes)
        return OpenAICompatibleLLMProvider(settings,
            reasoning_client=FakeChatClient('unused'),
            dialogue_client=FakeChatClient('unused')).preparation_cache_identity

    original = identity()
    assert identity(api_key=SecretStr('rotated-private-key')) == original
    assert identity(dialogue_model='another-flash') == original
    assert identity(reasoning_model='another-reasoner') != original
    assert identity(base_url='https://other.example.com/v1') != original
    assert 'rotated-private-key' not in identity(api_key=SecretStr('rotated-private-key'))


def test_settings_build_client_kwargs_with_thinking_disabled() -> None:
    settings = _settings(disable_thinking=True)

    reasoning_kwargs = settings.reasoning_client_kwargs()
    dialogue_kwargs = settings.dialogue_client_kwargs()

    assert reasoning_kwargs["base_url"] == "https://api.example.com/v1"
    assert reasoning_kwargs["model"] == "reasoning-model"
    assert dialogue_kwargs["model"] == "dialogue-model"
    assert reasoning_kwargs["extra_body"] is None
    assert dialogue_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert reasoning_kwargs["use_responses_api"] is False


def test_provider_parses_material_analysis() -> None:
    async def run_case() -> None:
        reasoning_client = FakeChatClient(
            '{"summary":"Short summary","keywords":["market"],'
            '"expressions":[{"text":"went to the market","meaning":"visited a market"}],'
            '"difficulties":["past tense"],"suggested_goals":["retell the material"],'
            '"topics":[{"title":"Market","opening_question":"Do you enjoy markets?","source_excerpt":"market",'
            '"answer_branches":[{"user_intent":"Likes markets","response_points":["market"],'
            '"suggested_reply":"I like them too.","follow_up":"What do you enjoy?","source_excerpts":["market"]}]}]}'
        )
        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=reasoning_client,
            dialogue_client=FakeChatClient("unused"),
        )

        analysis = await provider.analyze_material(
            material=_material(),
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
        )

        assert isinstance(analysis, MaterialAnalysis)
        assert analysis.summary == "Short summary"
        assert analysis.keywords == ["market"]
        assert analysis.expressions[0] == MaterialExpression(
            text="went to the market",
            meaning="visited a market",
            example=None,
        )
        assert analysis.difficulties == ["past tense"]
        assert analysis.suggested_goals == ["retell the material"]

    asyncio.run(run_case())


def test_provider_routes_generation_to_reasoning_client() -> None:
    async def run_case() -> None:
        reasoning_client = FakeChatClient("Practice one sentence.")
        dialogue_client = FakeChatClient("Dialogue response.")
        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=reasoning_client,
            dialogue_client=dialogue_client,
        )

        result = await provider.generate_task(
            material=_material(),
            learner_level=ProficiencyLevel.A2,
            target_language=LanguageEnum.ENGLISH,
        )

        assert result == "Practice one sentence."
        assert len(reasoning_client.calls) == 1
        assert dialogue_client.calls == []
        prompt_text = "\n".join(message.content for message in reasoning_client.calls[0])
        assert "Do not invent/add facts" in prompt_text
        assert "practice extension" in prompt_text

    asyncio.run(run_case())


def test_provider_routes_reply_to_dialogue_client() -> None:
    async def run_case() -> None:
        reasoning_client = FakeChatClient("Reasoning response.")
        dialogue_client = FakeChatClient("Good answer.")
        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=reasoning_client,
            dialogue_client=dialogue_client,
        )

        result = await provider.generate_reply(
            current_instruction=PracticeInstruction(prompt="Retell the material."),
            material=_material(),
            message_history=[],
            user_message=Message(role=MessageRole.USER, content="I went market."),
            corrections=[],
            target_language=LanguageEnum.ENGLISH,
        )

        assert result == "Good answer."
        assert reasoning_client.calls == []
        assert len(dialogue_client.calls) == 1

    asyncio.run(run_case())


def test_provider_parses_feedback_and_review_items() -> None:
    async def run_case() -> None:
        reasoning_client = FakeChatClient(
            "```json\n"
            '[{"error_type":"grammar","original":"I go","corrected":"I went",'
            '"explanation":"Use past tense."}]\n'
            "```"
        )
        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=reasoning_client,
            dialogue_client=FakeChatClient("unused"),
        )

        feedback = await provider.correct_answer(
            current_instruction=PracticeInstruction(prompt="Use past tense."),
            user_message=Message(role=MessageRole.USER, content="I go"),
            target_language=LanguageEnum.ENGLISH,
        )

        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=FakeChatClient(
                "```json\n"
                '[{"kind":"cloze","prompt":"I ___ home.","answer":"went"}]\n'
                "```"
            ),
            dialogue_client=FakeChatClient("unused"),
        )
        review_items = await provider.create_review_items(
            corrections=[feedback[0]],
            material=_material(),
        )

        assert isinstance(feedback[0], FeedbackItem)
        assert feedback[0].corrected == "I went"
        assert review_items[0].kind == ReviewItemKind.CLOZE
        assert review_items[0].answer == "went"

    asyncio.run(run_case())


def test_provider_parses_session_review() -> None:
    async def run_case() -> None:
        reasoning_client = FakeChatClient(
            "```json\n"
            '{"summary":"Use past tense more consistently.",'
            '"focus_areas":["simple past tense"],'
            '"feedback_items":[{"error_type":"grammar","original":"I go",'
            '"corrected":"I went","explanation":"Use past tense."}],'
            '"review_items":[{"kind":"cloze","prompt":"I ___ home.","answer":"went"}],'
            '"next_action":"Review tomorrow."}\n'
            "```"
        )
        provider = OpenAICompatibleLLMProvider(
            _settings(),
            reasoning_client=reasoning_client,
            dialogue_client=FakeChatClient("unused"),
        )

        review = await provider.summarize_session(
            session=PracticeSession(
                material_id="mat_1",
                pattern_id="guided_roleplay",
                profile=SessionUserProfile(
                    profile_level=ProficiencyLevel.A2,
                    native_language=LanguageEnum.CHINESE,
                    target_language=LanguageEnum.ENGLISH,
                ),
                messages=[Message(role=MessageRole.USER, content="I go home.")],
            ),
            material=_material(),
            target_language=LanguageEnum.ENGLISH,
        )

        assert review.summary == "Use past tense more consistently."
        assert review.focus_areas == ["simple past tense"]
        assert review.feedback_items[0].corrected == "I went"
        assert review.review_items[0].answer == "went"
        assert review.next_action == "Review tomorrow."

    asyncio.run(run_case())


def _settings(disable_thinking: bool = False) -> OpenAICompatibleLLMSettings:
    return OpenAICompatibleLLMSettings(
        api_key=SecretStr("test-key"),
        base_url="https://api.example.com/v1",
        reasoning_model="reasoning-model",
        dialogue_model="dialogue-model",
        disable_thinking=disable_thinking,
    )


def _material() -> LearningMaterial:
    return LearningMaterial(
        title="Market trip",
        source_language=LanguageEnum.ENGLISH,
        content="Yesterday I went to the market.",
    )


def test_truncated_dialogue_stream_is_not_a_complete_reply():
    from langchain_core.messages import AIMessageChunk
    import pytest

    class Truncated:
        async def astream(self, messages):
            yield AIMessageChunk(content="An unfinished", response_metadata={"finish_reason": "length"})
    async def run():
        provider = OpenAICompatibleLLMProvider(_settings(),
            reasoning_client=FakeChatClient("unused"), dialogue_client=Truncated())
        material = LearningMaterial(title="Book", source_language=LanguageEnum.ENGLISH, content="A friend returned.")
        user = Message(role=MessageRole.USER, content="Why did the friend return?")
        with pytest.raises(ValueError, match="未完成"):
            async for _ in provider.stream_reply(current_instruction=PracticeInstruction(prompt="Chat"),
                material=material, message_history=[user], user_message=user, corrections=[], target_language=LanguageEnum.ENGLISH):
                pass
    asyncio.run(run())
