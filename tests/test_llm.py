import asyncio

import pytest
from dotenv import load_dotenv

from lingualoop.core import (
    LanguageEnum,
    LearningMaterial,
    Message,
    MessageRole,
    ProficiencyLevel,
)
from lingualoop.engine.langgraph import build_learning_session_graph
from lingualoop.providers import OpenAICompatibleLLMProvider


def is_model_routing_error(error: Exception) -> bool:
    message = str(error)
    return "model_not_found" in message or "No available channel for model" in message


@pytest.mark.real_ai
def test_real_openai_compatible_provider_through_langgraph_smoke() -> None:
    # Collection and offline runs must not load personal service configuration.
    load_dotenv()

    async def run_case() -> None:
        provider = OpenAICompatibleLLMProvider.from_env()
        graph = build_learning_session_graph(provider)

        try:
            result = await graph.ainvoke(
                {
                    "material": LearningMaterial(
                        title="Market trip",
                        source_language=LanguageEnum.ENGLISH,
                        content="Yesterday I went to the market and bought apples.",
                    ),
                    "learner_level": ProficiencyLevel.A2,
                    "target_language": LanguageEnum.ENGLISH,
                    "user_message": Message(
                        role=MessageRole.USER,
                        content="Yesterday I go market and buy apple.",
                    ),
                }
            )
        except Exception as exc:
            if is_model_routing_error(exc):
                pytest.fail(
                    "Configured model is not available for the current API key "
                    "group. Set OPENAI_REASONING_MODEL and OPENAI_DIALOGUE_MODEL "
                    "to model ids returned by your OpenAI-compatible provider."
                )
            raise
        finally:
            await provider.aclose()

        assert result["current_instruction"].prompt.strip()
        assert isinstance(result["assistant_message"], str)
        assert result["assistant_message"].strip()
        assert isinstance(result["corrections"], list)
        assert isinstance(result["review_items"], list)

    asyncio.run(run_case())
