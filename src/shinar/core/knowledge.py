"""Provider-neutral, source-grounded knowledge and model usage contracts."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelBudgetExceeded(RuntimeError):
    """A persisted input/output/request reservation cannot be safely made."""


class SourceSpan(KnowledgeModel):
    id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class SourceSection(SourceSpan):
    label: str
    level: int = 1


class DiscussionScope(KnowledgeModel):
    material_id: str
    source_hash: str
    index_version: str = "source-view-v1"
    read_through: int = Field(gt=0)
    base: SourceSpan | None = None
    focus: SourceSpan | None = None
    focus_kind: Literal["paragraph", "text"] | None = None
    section_id: str | None = None
    label: str = ""
    quote: str = ""


class TurnSourceSnapshot(DiscussionScope):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceUnit(KnowledgeModel):
    id: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    content_hash: str
    source_kind: str = "unknown"
    section_path: str = ""
    paragraphs: list[SourceSpan] = Field(default_factory=list)


class GroundedNote(KnowledgeModel):
    id: str
    unit_id: str
    text: str
    support_ids: list[str]
    attribution: str
    statement_kind: Literal["narrated", "claim", "interpretation", "uncertain"]
    entities: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    dependency_ids: list[str] = Field(default_factory=list)
    knowledge_end: int = Field(ge=0)
    source_kind: str = "unknown"
    generation_version: str = "semantic-v1"


class BriefPoint(KnowledgeModel):
    text: str
    support_ids: list[str]


class ReadingBrief(KnowledgeModel):
    summary: str
    points: list[BriefPoint] = Field(default_factory=list)
    support_ids: list[str] = Field(default_factory=list)
    knowledge_end: int = Field(default=0, ge=0)


class MaterialKnowledge(KnowledgeModel):
    version: str = "semantic-v1"
    source_hash: str
    scope_end: int = Field(ge=0)
    status: Literal["saved", "preparing", "partial", "ready", "failed"] = "saved"
    units: list[SourceUnit] = Field(default_factory=list)
    notes: list[GroundedNote] = Field(default_factory=list)
    completed_unit_ids: list[str] = Field(default_factory=list)
    excluded_unit_ids: list[str] = Field(default_factory=list)
    brief: ReadingBrief | None = None
    errors: dict[str, str] = Field(default_factory=dict)
    generation_identity: str = ""


class MemoryItem(KnowledgeModel):
    text: str
    message_ids: list[str]
    speaker: Literal["user", "assistant"]
    kind: Literal["stance", "revision", "disagreement", "correction", "open_question", "closed"]


class ConversationMemory(KnowledgeModel):
    items: list[MemoryItem] = Field(default_factory=list)
    through_message_count: int = 0
    source_message_ids: list[str] = Field(default_factory=list)


class FocusReference(KnowledgeModel):
    key: str
    source_hash: str
    knowledge_end: int
    based_on_message_ids: list[str]
    points: list[BriefPoint] = Field(default_factory=list)
    facts: list[GroundedNote] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)


class TurnEvidence(KnowledgeModel):
    id: str
    text: str
    start_char: int
    end_char: int
    source_kind: str = "unknown"


class TurnContext(KnowledgeModel):
    prompt_version: str = "semantic-dialogue-v2"
    retrieval_version: str = "semantic-retrieval-v2"
    title: str
    scope_end: int
    source_hash: str
    brief: str = ""
    notes: list[GroundedNote] = Field(default_factory=list)
    evidence: list[TurnEvidence] = Field(default_factory=list)
    memory: list[MemoryItem] = Field(default_factory=list)
    focus_points: list[BriefPoint] = Field(default_factory=list)
    focus_key: str = ""
    gaps: list[str] = Field(default_factory=list)
    retrieval_ms: float = 0
    verification_ms: float = 0
    source_context: TurnSourceSnapshot | None = None


class ReasoningRequest(KnowledgeModel):
    payload: dict[str, Any]
    max_tokens: int = 4096
    deadline_seconds: float = 120


class ReasoningResponse(KnowledgeModel):
    content: str
    usage: dict[str, Any] = Field(default_factory=dict)


# Per-task diagnostics, never a process-global "last response" shared by roles.
# Adapters publish metadata only; the application owns persistence and budgets.
model_call_usage: ContextVar[dict[str, Any] | None] = ContextVar("model_call_usage", default=None)


def publish_usage(usage: dict[str, Any] | None, finish_reason: str | None = None) -> None:
    target = model_call_usage.get()
    if target is None:
        return
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = (usage or {}).get(key)
        if isinstance(value, int) and value >= 0:
            target[key] = value
    details = (usage or {}).get("output_token_details") or {}
    if isinstance(details.get("reasoning"), int):
        target["reasoning_tokens"] = details["reasoning"]
    if finish_reason:
        target["finish_reason"] = finish_reason
