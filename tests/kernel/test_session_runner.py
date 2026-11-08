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
    SessionEventType,
    SessionStatus,
    SessionUserProfile,
)
from shinar.kernel import DirectLearningSessionRunner, InMemoryEventStore


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
        return f"Retell '{material.title}' in {target_language.value} at {learner_level.value}."

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
        return [
            ReviewItem(
                prompt="Yesterday I ___ to the market.",
                answer="went",
                source_feedback_id=corrections[0].id,
            )
        ]

    async def summarize_session(
        self,
        *,
        session,
        material: LearningMaterial,
        target_language: LanguageEnum,
    ) -> SessionReview:
        return SessionReview(
            summary="Past tense needs attention.",
            focus_areas=["simple past tense"],
            feedback_items=session.feedback_items,
            review_items=[
                ReviewItem(
                    prompt="Yesterday I ___ to the market.",
                    answer="went",
                    source_feedback_id=session.feedback_items[0].id,
                )
            ],
            next_action="Review this later without looking at the answer.",
        )


class NoisyFeedbackProvider(FakeLearningLLMProvider):
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
                original="go",
                corrected="went",
                explanation="Use past tense.",
            ),
            FeedbackItem(
                error_type="grammar",
                original="go",
                corrected="went",
                explanation="Duplicate correction.",
            ),
            FeedbackItem(
                error_type="grammar",
                original="buy",
                corrected="bought",
                explanation="Use past tense.",
            ),
            FeedbackItem(
                error_type="vocabulary",
                original="apple",
                corrected="apples",
                explanation="Use plural form here.",
            ),
            FeedbackItem(
                error_type="fluency",
                original="market",
                corrected="the market",
                explanation="Use a natural noun phrase.",
            ),
        ]


def test_direct_runner_starts_session_with_plan_and_events() -> None:
    async def run_case() -> None:
        material = _material()
        store = InMemoryEventStore()
        runner = DirectLearningSessionRunner(FakeLearningLLMProvider(), store)

        result = await runner.start_session(
            material=material,
            profile=_profile(),
        )

        assert result.session.material_id == material.id
        assert result.session.current_instruction is not None
        assert result.session.current_instruction.prompt.startswith("Retell")
        assert result.assistant_message == result.session.messages[0]
        assert [event.event_type for event in result.events] == [
            SessionEventType.SESSION_STARTED,
            SessionEventType.ASSISTANT_MESSAGE_ADDED,
        ]
        assert await store.list_session_events(result.session.id) == result.events

    asyncio.run(run_case())


def test_direct_runner_handles_user_message_without_final_review_items() -> None:
    async def run_case() -> None:
        material = _material()
        store = InMemoryEventStore()
        runner = DirectLearningSessionRunner(FakeLearningLLMProvider(), store)
        started = await runner.start_session(
            material=material,
            profile=_profile(),
        )

        result = await runner.handle_user_message(
            session=started.session,
            material=material,
            user_content="Yesterday I go to market.",
        )

        user_message = result.session.messages[1]
        assert len(result.session.messages) == 3
        assert result.assistant_message is not None
        assert result.assistant_message.content == "Good start. Use past tense here."
        assert result.feedback_items[0].source_message_id == user_message.id
        assert result.review_items == []
        assert result.session.review_items == []
        assert [event.event_type for event in result.events] == [
            SessionEventType.USER_MESSAGE_ADDED,
            SessionEventType.ASSISTANT_MESSAGE_ADDED,
            SessionEventType.FEEDBACK_CREATED,
        ]
        assert len(await store.list_session_events(started.session.id)) == 5

    asyncio.run(run_case())


def test_direct_runner_dedupes_and_limits_feedback_items() -> None:
    async def run_case() -> None:
        material = _material()
        store = InMemoryEventStore()
        runner = DirectLearningSessionRunner(NoisyFeedbackProvider(), store)
        started = await runner.start_session(material=material, profile=_profile())

        result = await runner.handle_user_message(
            session=started.session,
            material=material,
            user_content="Yesterday I go to market and buy apple.",
        )

        correction_pairs = [(item.original, item.corrected) for item in result.feedback_items]
        assert correction_pairs == [("go", "went"), ("buy", "bought"), ("apple", "apples")]
        assert len(result.session.feedback_items) == 3
        assert all(item.source_message_id is not None for item in result.feedback_items)

    asyncio.run(run_case())


def test_direct_runner_completes_session_with_review_items() -> None:
    async def run_case() -> None:
        material = _material()
        store = InMemoryEventStore()
        runner = DirectLearningSessionRunner(FakeLearningLLMProvider(), store)
        started = await runner.start_session(material=material, profile=_profile())
        answered = await runner.handle_user_message(
            session=started.session,
            material=material,
            user_content="Yesterday I go to market.",
        )

        result = await runner.complete_session(session=answered.session, material=material)

        assert result.session.status is SessionStatus.COMPLETED
        assert result.session.completed_at is not None
        assert result.session.review is not None
        assert result.review_items[0].source_session_id == result.session.id
        assert result.review_items[0].source_material_id == material.id
        assert [event.event_type for event in result.events] == [
            SessionEventType.REVIEW_ITEMS_CREATED,
            SessionEventType.SESSION_COMPLETED,
        ]

    asyncio.run(run_case())


def _material() -> LearningMaterial:
    return LearningMaterial(
        title="Market trip",
        source_language=LanguageEnum.CHINESE,
        content="Yesterday I went to the market.",
    )


def _profile() -> SessionUserProfile:
    return SessionUserProfile(
        profile_level=ProficiencyLevel.A2,
        native_language=LanguageEnum.CHINESE,
        target_language=LanguageEnum.ENGLISH,
    )
