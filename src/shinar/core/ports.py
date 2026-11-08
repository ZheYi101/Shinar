from collections.abc import AsyncIterator
from typing import Protocol

from shinar.core.knowledge import ReasoningRequest, ReasoningResponse


from shinar.core.domain import (
    DialoguePreparation,
    DiscussionTopic,
    FeedbackItem,
    LanguageEnum,
    LearningMaterial,
    MaterialAnalysis,
    Message,
    PracticeInstruction,
    PracticeOptions,
    PracticeSession,
    ProficiencyLevel,
    ReviewItem,
    SessionEvent,
    SessionReview,
)


class MaterialReasoningProvider(Protocol):
    """Independent, bounded reasoning operations; foreground text is a separate role."""

    async def prepare_source_unit(self, request: ReasoningRequest) -> ReasoningResponse: ...

    async def summarize_reading(self, request: ReasoningRequest) -> ReasoningResponse: ...

    async def prepare_focus(self, request: ReasoningRequest) -> ReasoningResponse: ...

    async def summarize_conversation(self, request: ReasoningRequest) -> ReasoningResponse: ...


class LearningLLMProvider(Protocol):
    """Provider-neutral learning operations shared by runners and adapters.

    Replies use the dialogue role; analysis and preparation use the reasoning role.
    Audio and transport capabilities are separate ports.
    """

    async def analyze_material(
        self,
        *,
        material: LearningMaterial,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
    ) -> MaterialAnalysis: ...

    async def generate_task(
        self,
        *,
        material: LearningMaterial,
        learner_level: ProficiencyLevel,
        target_language: LanguageEnum,
        topic: DiscussionTopic | None = None,
        options: PracticeOptions | None = None,
    ) -> str: ...

    async def generate_reply(
        self,
        *,
        current_instruction: PracticeInstruction,
        material: LearningMaterial,
        message_history: list[Message],
        user_message: Message,
        corrections: list[FeedbackItem],
        target_language: LanguageEnum,
    ) -> str: ...

    def stream_reply(
        self,
        *,
        current_instruction: PracticeInstruction,
        material: LearningMaterial,
        message_history: list[Message],
        user_message: Message,
        corrections: list[FeedbackItem],
        target_language: LanguageEnum,
    ) -> AsyncIterator[str]: ...

    async def prepare_custom_topic(
        self,
        *,
        material: LearningMaterial,
        title: str,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
    ) -> DiscussionTopic: ...

    async def prepare_dialogue(
        self, *, material: LearningMaterial, session: PracticeSession
    ) -> DialoguePreparation: ...

    async def correct_answer(
        self,
        *,
        current_instruction: PracticeInstruction,
        user_message: Message,
        target_language: LanguageEnum,
    ) -> list[FeedbackItem]: ...

    async def create_review_items(
        self,
        *,
        corrections: list[FeedbackItem],
        material: LearningMaterial,
    ) -> list[ReviewItem]: ...

    async def summarize_session(
        self,
        *,
        session: PracticeSession,
        material: LearningMaterial,
        target_language: LanguageEnum,
    ) -> SessionReview: ...


class EventStore(Protocol):
    async def append(self, event: SessionEvent) -> None: ...

    async def append_many(self, events: list[SessionEvent]) -> None: ...

    async def list_session_events(self, session_id: str) -> list[SessionEvent]: ...
