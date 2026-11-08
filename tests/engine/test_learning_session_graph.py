import asyncio

from shinar.core import (
    FeedbackItem,
    LanguageEnum,
    LearningMaterial,
    MaterialAnalysis,
    Message,
    PracticeInstruction,
    ProficiencyLevel,
    ReviewItem,
    SessionReview,
    MessageRole,
)
from shinar.engine.langgraph import build_learning_session_graph


class FakeLearningLLMProvider:
    async def analyze_material(
        self,
        *,
        material: LearningMaterial,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
    ) -> MaterialAnalysis:
        return MaterialAnalysis(
            summary="Mock summary.",
            keywords=[],
            expressions=[],
            difficulties=[],
            suggested_goals=[],
        )

    async def generate_task(
        self,
        *,
        material: LearningMaterial,
        learner_level: ProficiencyLevel,
        target_language: LanguageEnum,
    ) -> str:
        return "Retell the material in one sentence."

    async def correct_answer(
        self,
        *,
        current_instruction: PracticeInstruction,
        user_message: Message,
        target_language: LanguageEnum,
    ) -> list[FeedbackItem]:
        return [
            FeedbackItem(
                error_type="grammar",
                original=user_message.content,
                corrected="Yesterday I went to the market.",
                explanation="Use past tense with yesterday.",
            )
        ]

    async def generate_reply(
        self,
        *,
        current_instruction: PracticeInstruction,
        material: LearningMaterial,
        message_history: list[Message],
        user_message: Message,
        corrections: list[FeedbackItem],
        target_language: LanguageEnum,
    ) -> str:
        return "Good start. Use past tense here."

    async def create_review_items(
        self,
        *,
        corrections: list[FeedbackItem],
        material: LearningMaterial,
    ) -> list[ReviewItem]:
        return [ReviewItem(prompt="Yesterday I ___ to the market.", answer="went")]

    async def summarize_session(
        self,
        *,
        session,
        material: LearningMaterial,
        target_language: LanguageEnum,
    ) -> SessionReview:
        return SessionReview(summary="Summary", review_items=[])


def test_langgraph_learning_session_smoke() -> None:
    async def run_case() -> None:
        material = LearningMaterial(
            title="Market trip",
            source_language=LanguageEnum.CHINESE,
            content="Yesterday I went to the market.",
        )
        graph = build_learning_session_graph(FakeLearningLLMProvider())

        result = await graph.ainvoke(
            {
                "material": material,
                "learner_level": ProficiencyLevel.A2,
                "target_language": LanguageEnum.ENGLISH,
                "user_message": Message(
                    role=MessageRole.USER,
                    content="Yesterday I go to market.",
                ),
            }
        )

        assert result["current_instruction"].prompt == (
            "Retell the material in one sentence."
        )
        assert result["assistant_message"] == "Good start. Use past tense here."
        assert len(result["corrections"]) == 1
        assert len(result["review_items"]) == 1

    asyncio.run(run_case())


def test_graph_streams_intermediate_updates() -> None:
    async def run_case() -> None:
        graph = build_learning_session_graph(FakeLearningLLMProvider())

        updates = []
        async for update in graph.astream(
            {
                "material": _material(),
                "learner_level": ProficiencyLevel.A2,
                "target_language": LanguageEnum.ENGLISH,
                "user_message": Message(
                    role=MessageRole.USER,
                    content="Yesterday I go to market.",
                ),
            },
            stream_mode="updates",
        ):
            updates.append(update)

        assert "create_task" in updates[0]
        assert "current_instruction" in updates[0]["create_task"]

        assert "correct_answer" in updates[1]
        assert "corrections" in updates[1]["correct_answer"]

        assert "generate_reply" in updates[2]
        assert "assistant_message" in updates[2]["generate_reply"]

        assert "create_review_items" in updates[3]
        assert "review_items" in updates[3]["create_review_items"]

    asyncio.run(run_case())


def _material() -> LearningMaterial:
    return LearningMaterial(
        title="Market trip",
        source_language=LanguageEnum.CHINESE,
        content="Yesterday I went to the market.",
    )
