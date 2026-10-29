from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lingualoop.core.knowledge import (
    MaterialKnowledge, ConversationMemory, FocusReference, SourceSection, TurnSourceSnapshot,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _clean_required_text(value: str | StrEnum) -> str | StrEnum:
    if isinstance(value, StrEnum):
        return value
    value = value.strip()
    if not value:
        raise ValueError("required text fields must not be blank")
    return value


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Language ability level(A1 is lowest)
class ProficiencyLevel(StrEnum):
    """user's ability of target language"""

    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"
    UNKNOWN = "unknown"


class SessionUserProfile(DomainModel):
    """a profile used in a specific session"""

    profile_level: ProficiencyLevel
    native_language: LanguageEnum
    target_language: LanguageEnum


class CorrectionIntensity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FeedbackTiming(StrEnum):
    END = "end"
    IMMEDIATE = "immediate"
    OFF = "off"


class PracticeMode(StrEnum):
    DISCUSSION = "discussion"
    ROLEPLAY = "roleplay"


class PracticeOptions(DomainModel):
    mode: PracticeMode = PracticeMode.DISCUSSION
    difficulty: ProficiencyLevel = ProficiencyLevel.UNKNOWN
    correction_intensity: CorrectionIntensity = CorrectionIntensity.LOW
    feedback_timing: FeedbackTiming = FeedbackTiming.END
    role_description: str = ""
    read_through: int | None = Field(default=None, ge=0)


class AnswerBranch(DomainModel):
    user_intent: str
    response_points: list[str] = Field(default_factory=list)
    suggested_reply: str = ""
    follow_up: str = ""
    source_excerpts: list[str] = Field(default_factory=list)


class MaterialCharacter(DomainModel):
    name: str
    description: str = ""
    source_excerpts: list[str] = Field(default_factory=list)


class PreparedChunk(DomainModel):
    id: str = Field(default_factory=lambda: new_id("chunk"))
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    summary: str
    source_excerpt: str
    content_hash: str = ""
    analysis_payload: dict[str, Any] = Field(default_factory=dict)


class DiscussionTopic(DomainModel):
    id: str = Field(default_factory=lambda: new_id("topic"))
    title: str
    opening_question: str
    source_excerpt: str
    category: str = "discussion"
    answer_branches: list[AnswerBranch] = Field(default_factory=list)
    source_chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("title", "opening_question", "source_excerpt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return str(_clean_required_text(value))


class SubtitleCue(DomainModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str


class MaterialSourceType(StrEnum):
    TEXT = "text"
    ARTICLE = "article"
    SUBTITLE = "subtitle"
    CHAT_LOG = "chat_log"
    NOTE = "note"
    OTHER = "other"


class MaterialTrack(StrEnum):
    LIVE_CHAT = "live_chat"
    ARTICLE_READING = "article_reading"


class NormalizationStatus(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class FeedbackType(StrEnum):
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    FLUENCY = "fluency"
    PRAGMATICS = "pragmatics"
    OTHER = "other"


class ReviewItemKind(StrEnum):
    CLOZE = "cloze"  # Fill-in-the-Blank
    REWRITE = "rewrite"
    RECALL = "recall"
    EXPRESSION = "expression"


class ReviewStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    IGNORED = "ignored"
    ARCHIVED = "archived"
    DELETED = "deleted"
    MASTERED = "mastered"


class ReviewRating(StrEnum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class SessionEventType(StrEnum):
    SESSION_STARTED = "session.started"
    USER_MESSAGE_ADDED = "message.user_added"
    ASSISTANT_MESSAGE_ADDED = "message.assistant_added"
    FEEDBACK_CREATED = "feedback.created"
    REVIEW_ITEMS_CREATED = "review_items.created"
    SESSION_COMPLETED = "session.completed"
    REVIEW_OUTCOME_RECORDED = "review.outcome_recorded"
    REVIEW_PAUSED = "review.paused"
    REVIEW_IGNORED = "review.ignored"
    REVIEW_ARCHIVED = "review.archived"
    REVIEW_DELETED = "review.deleted"


class LanguageEnum(StrEnum):
    """contain all supported language(in fact just randomly listed)"""

    CHINESE = "chinese"
    ENGLISH = "english"
    JAPANESE = "japanese"
    FRENCH = "french"
    GERMANY = "germany"
    SPANISH = "spanish"


class CapabilityRequirement(DomainModel):
    name: str
    min_version: str = "1.0"
    optional: bool = False


class UserProfile(DomainModel):
    id: str = Field(default_factory=lambda: new_id("user"))
    native_language: LanguageEnum
    target_language: LanguageEnum
    learner_level: ProficiencyLevel = ProficiencyLevel.UNKNOWN
    correction_intensity: CorrectionIntensity = CorrectionIntensity.MEDIUM
    goals: list[str] = Field(default_factory=list)

    @field_validator("native_language", "target_language")
    @classmethod
    def _language_must_not_be_blank(
        cls, value: str | LanguageEnum
    ) -> str | LanguageEnum:
        return _clean_required_text(value)


class MaterialExpression(DomainModel):
    text: str
    meaning: str | None = None
    example: str | None = None


class MaterialAnalysis(DomainModel):
    summary: str
    keywords: list[str] = Field(default_factory=list)
    expressions: list[MaterialExpression] = Field(default_factory=list)
    difficulties: list[str] = Field(default_factory=list)
    suggested_goals: list[str] = Field(default_factory=list)
    topics: list[DiscussionTopic] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    characters: list[MaterialCharacter] = Field(default_factory=list)
    chunks: list[PreparedChunk] = Field(default_factory=list)
    preparation_complete: bool = True
    overview_complete: bool = False
    preparation_strategy: str = "legacy"
    scope_end: int | None = Field(default=None, ge=0)
    knowledge: MaterialKnowledge | None = None


class DialoguePreparation(DomainModel):
    based_on_message_count: int
    predicted_intents: list[str] = Field(default_factory=list)
    suggested_directions: list[str] = Field(default_factory=list)
    response_points: list[str] = Field(default_factory=list)
    source_excerpts: list[str] = Field(default_factory=list)


class ReplyTiming(DomainModel):
    ttft_ms: float | None = None
    total_ms: float
    streamed: bool = False
    context_ms: float = 0
    verification_ms: float = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


class LearningMaterial(DomainModel):
    id: str = Field(default_factory=lambda: new_id("mat"))
    title: str
    source_language: LanguageEnum
    content: str
    source_type: MaterialSourceType = MaterialSourceType.TEXT
    raw_content: str | None = None
    normalized_content: str | None = None
    track: MaterialTrack = MaterialTrack.ARTICLE_READING
    source_path: str | None = None
    normalization_status: NormalizationStatus = NormalizationStatus.RAW
    analysis: MaterialAnalysis | None = None
    analysis_cache_key: str | None = None
    full_analysis_cache_key: str | None = None
    source_hash: str = ""
    source_sections: list[SourceSection] = Field(default_factory=list)
    # None preserves whole-material access for existing libraries; 0 is unconfirmed.
    read_through: int | None = Field(default=None, ge=0)
    profile: SessionUserProfile | None = None
    subtitle_cues: list[SubtitleCue] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    imported_at: datetime = Field(default_factory=utc_now)

    @field_validator("title", "content", "source_language")
    @classmethod
    def _required_text_must_not_be_blank(
        cls, value: str | LanguageEnum
    ) -> str | LanguageEnum:
        return _clean_required_text(value)


class LearningSegment(DomainModel):
    id: str = Field(default_factory=lambda: new_id("segment"))
    material_id: str
    content: str
    start_ref: int | None = None
    end_ref: int | None = None
    context_summary: str | None = None
    practice_goal: str | None = None


class PracticeInstruction(DomainModel):
    """a concrete practice instruction produced by ai,
    which equals to a small task to practice, inside a `PracticeSession`"""

    id: str = Field(default_factory=lambda: new_id("instruction"))
    prompt: str
    expected_output: str | None = None
    focus_points: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PracticePlan(DomainModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    pattern_id: str
    title: str
    instructions: list[PracticeInstruction] = Field(default_factory=list)


class Message(DomainModel):
    """refer to all sentences shown in the chat block, no matter by human or ai"""

    id: str = Field(default_factory=lambda: new_id("msg"))
    role: MessageRole
    content: str
    created_at: datetime = Field(default_factory=utc_now)
    feedback_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_context: TurnSourceSnapshot | None = None

    @field_validator("content")
    @classmethod
    def _content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message content must not be blank")
        return value


class FeedbackItem(DomainModel):
    id: str = Field(default_factory=lambda: new_id("feedback"))
    error_type: FeedbackType | str = FeedbackType.OTHER
    original: str
    corrected: str
    explanation: str
    source_message_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ReviewItem(DomainModel):
    id: str = Field(default_factory=lambda: new_id("review"))
    kind: ReviewItemKind = ReviewItemKind.CLOZE
    prompt: str
    answer: str
    source_feedback_id: str | None = None
    source_session_id: str | None = None
    source_material_id: str | None = None
    source_segment_id: str | None = None
    source_message_id: str | None = None
    context: str | None = None
    status: ReviewStatus = ReviewStatus.ACTIVE
    due_at: datetime | None = Field(default_factory=lambda: utc_now() + timedelta(days=1))
    created_at: datetime = Field(default_factory=utc_now)


class ReviewOutcome(DomainModel):
    id: str = Field(default_factory=lambda: new_id("review_outcome"))
    review_item_id: str
    rating: ReviewRating
    answer: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    next_due_at: datetime | None = None


class SessionReview(DomainModel):
    summary: str
    focus_areas: list[str] = Field(default_factory=list)
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    next_action: str | None = None


class PracticeSession(DomainModel):
    id: str = Field(default_factory=lambda: new_id("session"))
    material_id: str
    pattern_id: str
    profile: SessionUserProfile
    # None denotes a legacy session; retain its original per-turn feedback.
    options: PracticeOptions | None = None
    topic: DiscussionTopic | None = None
    preparation: DialoguePreparation | None = None
    reference_refresh_count: int = Field(default=0, ge=0)
    reference_source_key: str = ""
    conversation_memory: ConversationMemory | None = None
    focus_reference: FocusReference | None = None
    initial_focus: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    plan: PracticePlan | None = None
    messages: list[Message] = Field(default_factory=list)
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    review: SessionReview | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @property
    def current_instruction(self) -> PracticeInstruction | None:
        if self.plan is None or not self.plan.instructions:
            return None
        return self.plan.instructions[-1]  # return the latest instruction


class SessionSummary(DomainModel):
    """Read-only navigation projection; never carries full messages or preparation."""

    id: str
    material_id: str
    title: str
    preview: str = ""
    turns: int = 0
    status: SessionStatus
    updated_at: datetime

    @classmethod
    def from_session(cls, session: PracticeSession) -> SessionSummary:
        return cls(
            id=session.id,
            material_id=session.material_id,
            title=session.topic.title if session.topic else next(
                (message.content for message in session.messages if message.role is MessageRole.USER),
                "",
            ),
            preview=next(
                (message.content[:140] for message in reversed(session.messages)
                 if message.role is MessageRole.ASSISTANT), "",
            ),
            turns=sum(message.role is MessageRole.USER for message in session.messages),
            status=session.status,
            updated_at=session.updated_at,
        )


class SessionEvent(DomainModel):
    id: str = Field(default_factory=lambda: new_id("event"))
    session_id: str
    event_type: SessionEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class PatternManifest(DomainModel):
    id: str
    name: str
    description: str
    required_capabilities: list[str] = Field(default_factory=list)


class PluginManifest(DomainModel):
    id: str
    name: str
    version: str
    provided_capabilities: list[str] = Field(default_factory=list)
