from __future__ import annotations

from pydantic import BaseModel, Field
from time import perf_counter
from typing import Callable

from shinar.core.domain import (
    FeedbackItem,
    LearningMaterial,
    Message,
    MessageRole,
    PracticeInstruction,
    PracticePlan,
    PracticeSession,
    ProficiencyLevel,
    ReviewItem,
    SessionEvent,
    SessionEventType,
    SessionUserProfile,
    SessionStatus,
    utc_now,
    DiscussionTopic,
    PracticeOptions,
    PracticeMode,
    FeedbackTiming,
    SessionReview,
    ReplyTiming,
)
from shinar.core.ports import EventStore, LearningLLMProvider
from shinar.core.preparation_validation import validate_dialogue_preparation
from shinar.core.knowledge import TurnContext, TurnSourceSnapshot, model_call_usage

DEFAULT_PATTERN_ID = "guided_roleplay"


class SessionStepResult(BaseModel):
    turn_id: str | None = None
    session: PracticeSession
    events: list[SessionEvent] = Field(default_factory=list)
    assistant_message: Message | None = None
    feedback_items: list[FeedbackItem] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    timing: ReplyTiming | None = None


class DirectLearningSessionRunner:
    """Deterministic business runner before LangGraph owns orchestration."""

    def __init__(
        self, llm_provider: LearningLLMProvider, event_store: EventStore
    ) -> None:
        self._llm_provider = llm_provider
        self._event_store = event_store

    async def start_session(
        self,
        *,
        material: LearningMaterial,
        profile: SessionUserProfile,
        pattern_id: str = DEFAULT_PATTERN_ID,
        topic: DiscussionTopic | None = None,
        options: PracticeOptions | None = None,
    ) -> SessionStepResult:
        if options and options.mode is PracticeMode.ROLEPLAY and not options.role_description.strip():
            raise ValueError("请描述你和 AI 各自的角色。")
        if topic and (not options or options.mode is PracticeMode.DISCUSSION):
            task_prompt = topic.opening_question
        elif topic:
            task_prompt = await self._llm_provider.generate_task(
                material=material, learner_level=profile.profile_level,
                target_language=profile.target_language, topic=topic, options=options,
            )
        elif options and options.mode is PracticeMode.DISCUSSION:
            task_prompt = _free_chat_opening(profile.target_language.value)
        else:  # Existing integrations without options retain the original task API.
            task_prompt = await self._llm_provider.generate_task(
                material=material, learner_level=profile.profile_level,
                target_language=profile.target_language,
                **({"options": options} if options else {}),
            )
        if options:
            pattern_id = ("topic-discussion" if topic else "free-discussion") if options.mode is PracticeMode.DISCUSSION else "guided_roleplay"

        instruction = PracticeInstruction(
            prompt=task_prompt,
            focus_points=_focus_points_from_material(material),
            metadata={"options": options.model_dump(mode="json") if options else None,
                      "topic": topic.model_dump(mode="json") if topic else None},
        )

        plan = PracticePlan(
            pattern_id=pattern_id,
            title=f"{material.title} practice",
            instructions=[instruction],
        )

        assistant_message = Message(role=MessageRole.ASSISTANT, content=task_prompt)

        session = PracticeSession(
            material_id=material.id,
            pattern_id=pattern_id,
            plan=plan,
            profile=profile,
            messages=[assistant_message],
            options=options,
            topic=topic,
        )

        events = [
            SessionEvent(
                session_id=session.id,
                event_type=SessionEventType.SESSION_STARTED,
                payload={
                    "material_id": material.id,
                    "pattern_id": pattern_id,
                    "learner_level": str(profile.profile_level),
                    "plan_id": plan.id,
                },
            ),
            message_event(session.id, assistant_message),
        ]
        await self._event_store.append_many(events)
        return SessionStepResult(
            session=session, events=events, assistant_message=assistant_message
        )

    async def handle_user_message(
        self, *, session: PracticeSession, material: LearningMaterial, user_content: str,
        on_delta: Callable[[str], None] | None = None,
        turn_context: TurnContext | None = None,
        source_context: TurnSourceSnapshot | None = None,
        confirmed_user: Message | None = None,
        persist_events: bool = True,
    ) -> SessionStepResult:
        instruction = session.current_instruction
        if instruction is None:
            raise ValueError("Practice session must have an active instruction")

        user_message = confirmed_user or Message(role=MessageRole.USER, content=user_content, source_context=source_context)
        corrections = await self._turn_feedback(session, user_message, user_content)
        reply_kwargs = self._reply_arguments(session, material, user_message, corrections, turn_context)
        started = perf_counter()
        first_token = None
        stream = getattr(self._llm_provider, "stream_reply", None)
        streamed = stream is not None and getattr(self._llm_provider, "supports_streaming", True)
        if stream:
            parts = []
            async for part in stream(**reply_kwargs):
                if not part:
                    continue
                if first_token is None:
                    first_token = perf_counter()
                parts.append(part)
                if on_delta:
                    on_delta(part)
            assistant_text = "".join(parts).strip()
        else:
            assistant_text = await self._llm_provider.generate_reply(**reply_kwargs)
            if on_delta and assistant_text:
                on_delta(assistant_text)
        if not assistant_text.strip():
            raise ValueError("对话服务未返回文字或回复未完成，请重试回复。")
        usage = model_call_usage.get() or {}
        timing = ReplyTiming(ttft_ms=(first_token-started)*1000 if first_token and streamed else None,
                             total_ms=(perf_counter()-started)*1000, streamed=streamed,
                             context_ms=turn_context.retrieval_ms if turn_context else 0,
                             verification_ms=turn_context.verification_ms if turn_context else 0,
                             input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))

        audit = {"timing": timing.model_dump(mode="json")}
        if turn_context:
            audit["context"] = {"scope_end": turn_context.scope_end,
                "prompt_version": turn_context.prompt_version,
                "retrieval_version": turn_context.retrieval_version,
                "evidence_ids": [item.id for item in turn_context.evidence],
                "note_ids": [note.id for note in turn_context.notes], "gaps": turn_context.gaps,
                "background_included": bool(turn_context.focus_points),
                "memory_message_ids": [value for item in turn_context.memory for value in item.message_ids]}
        assistant_message = Message(role=MessageRole.ASSISTANT, content=assistant_text, metadata=audit)

        updated_session = session.model_copy(
            update={
                "messages": [*session.messages, user_message, assistant_message],
                "feedback_items": [*session.feedback_items, *corrections],
                "updated_at": utc_now(),
            }
        )

        events = ([] if confirmed_user else [message_event(updated_session.id, user_message)])
        events.append(message_event(updated_session.id, assistant_message))

        if corrections:
            events.append(
                SessionEvent(
                    session_id=updated_session.id,
                    event_type=SessionEventType.FEEDBACK_CREATED,
                    payload={
                        "feedback_ids": [item.id for item in corrections],
                    },
                )
            )

        if persist_events:
            await self._event_store.append_many(events)

        return SessionStepResult(
            session=updated_session,
            events=events,
            assistant_message=assistant_message,
            feedback_items=corrections,
            timing=timing,
        )


    async def _turn_feedback(self, session, user_message, user_content):
        instruction = session.current_instruction
        corrections = []
        # New discussions keep reasoning off the foreground path. End-of-session feedback
        # remains grounded in confirmed user messages. Legacy direct integrations retain behaviour.
        if session.options is None:
            try:
                corrections = await self._llm_provider.correct_answer(
                    current_instruction=instruction, user_message=user_message,
                    target_language=session.profile.target_language,
                )
            except Exception:
                # Feedback is auxiliary; a failed correction must not block the reply.
                corrections = []

        corrections = [
            (
                item
                if item.source_message_id is not None
                else item.model_copy(update={"source_message_id": user_message.id})
            )
            for item in corrections
        ]
        if session.options:
            corrections = [item.model_copy(update={"source_message_id": user_message.id}) for item in corrections
                           if item.original.casefold() in user_content.casefold()
                           and item.original.casefold() != item.corrected.casefold()]
        feedback_limit = _feedback_limit(session)
        corrections = _dedupe_feedback_items(corrections, limit=feedback_limit)

        return corrections

    def _reply_arguments(self, session, material, user_message, corrections, turn_context):
        instruction = session.current_instruction
        preparation = session.preparation
        metadata = dict(instruction.metadata)
        if turn_context is not None:
            metadata["turn_context"] = turn_context.model_dump(mode="json")
        if preparation and preparation.based_on_message_count == len(session.messages):
            try:
                validated = validate_dialogue_preparation(preparation, material.content)
                metadata["preparation"] = validated.model_dump(mode="json")
            except ValueError:
                metadata.pop("preparation", None)
        else:
            metadata.pop("preparation", None)
        reply_instruction = instruction.model_copy(update={"metadata": metadata})
        return dict(
            current_instruction=reply_instruction,
            material=material,
            message_history=[*session.messages, user_message],
            user_message=user_message,
            corrections=corrections,
            target_language=session.profile.target_language,
        )

    async def complete_session(
        self,
        *,
        session: PracticeSession,
        material: LearningMaterial,
    ) -> SessionStepResult:
        if session.status is SessionStatus.COMPLETED:
            return SessionStepResult(session=session, review_items=session.review_items)

        user_messages = [m for m in session.messages if m.role is MessageRole.USER]
        if not user_messages:
            review = SessionReview(summary="本次尚未提交发言。可以随时围绕材料开始新的讨论。")
        elif session.options and session.options.feedback_timing is FeedbackTiming.OFF:
            review = SessionReview(summary=f"已完成 {len(user_messages)} 次发言，本轮未启用纠错与复习建议。")
        else:
            review = await self._llm_provider.summarize_session(
                session=session, material=material,
                target_language=session.profile.target_language,
            )
        if session.options:
            grounded = []
            for item in [*session.feedback_items, *review.feedback_items]:
                source = next((m for m in user_messages
                               if (item.source_message_id is None or m.id == item.source_message_id)
                               and item.original.casefold() in m.content.casefold()), None)
                if source and item.original.strip().casefold() != item.corrected.strip().casefold():
                    grounded.append(item.model_copy(update={"source_message_id": source.id}))
            feedback = _dedupe_feedback_items(grounded, limit=_feedback_limit(session))
            ids = {m.id for m in user_messages}
            feedback_ids = {item.id for item in feedback}
            candidates = [item for item in review.review_items
                          if item.source_message_id in ids or item.source_feedback_id in feedback_ids][:3]
            review = review.model_copy(update={"feedback_items": feedback, "review_items": candidates,
                                               "focus_areas": review.focus_areas[:3]})
        review_items = [
            item.model_copy(
                update={
                    "source_session_id": item.source_session_id or session.id,
                    "source_material_id": item.source_material_id or material.id,
                }
            )
            for item in review.review_items
        ]
        review = review.model_copy(
            update={
                "feedback_items": review.feedback_items if session.options else [*session.feedback_items, *review.feedback_items],
                "review_items": review_items,
            }
        )
        completed = session.model_copy(
            update={
                "status": SessionStatus.COMPLETED,
                "review": review,
                "review_items": review_items,
                "feedback_items": review.feedback_items,
                "updated_at": utc_now(),
                "completed_at": utc_now(),
            }
        )
        events = [
            SessionEvent(
                session_id=completed.id,
                event_type=SessionEventType.REVIEW_ITEMS_CREATED,
                payload={"review_item_ids": [item.id for item in review_items]},
            ),
            SessionEvent(
                session_id=completed.id,
                event_type=SessionEventType.SESSION_COMPLETED,
                payload={"summary": review.summary},
            ),
        ]
        await self._event_store.append_many(events)
        return SessionStepResult(
            session=completed,
            events=events,
            feedback_items=review.feedback_items,
            review_items=review_items,
        )

    async def handler_user_message(
        self, *, session: PracticeSession, material: LearningMaterial, user_content: str
    ) -> SessionStepResult:
        return await self.handle_user_message(
            session=session, material=material, user_content=user_content
        )


def _focus_points_from_material(material: LearningMaterial) -> list[str]:
    if material.analysis is None:
        return []

    return [
        *material.analysis.keywords,
        *[expr.text for expr in material.analysis.expressions],
    ]


def _feedback_limit(session: PracticeSession) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(
        session.options.correction_intensity.value if session.options else "high", 3)


def _dedupe_feedback_items(items: list[FeedbackItem], *, limit: int) -> list[FeedbackItem]:
    keyed: dict[tuple[str, str], FeedbackItem] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = (_normalize_feedback_text(item.original), _normalize_feedback_text(item.corrected))
        if key not in keyed:
            keyed[key] = item
            order.append(key)
            continue
        if keyed[key].source_message_id is None and item.source_message_id is not None:
            keyed[key] = item
    return [keyed[key] for key in order[:limit]]


def _normalize_feedback_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def message_event(session_id: str, message: Message) -> SessionEvent:
    event_type = (
        SessionEventType.USER_MESSAGE_ADDED
        if message.role == MessageRole.USER
        else SessionEventType.ASSISTANT_MESSAGE_ADDED
    )

    return SessionEvent(
        session_id=session_id,
        event_type=event_type,
        payload={
            "message_id": message.id,
            "role": message.role.value,
            "content": message.content,
        },
    )


def _free_chat_opening(language: str) -> str:
    return {
        "chinese": "读到这里，有什么让你特别在意的地方？我们就从那里聊起。",
        "japanese": "ここまで読んで、何がいちばん気になった？そこから話そう。",
        "english": "What has stayed with you in the part you’ve read? We can start there.",
        "french": "Qu’est-ce qui t’a marqué dans ce que tu as lu ?",
        "germany": "Was ist dir in dem gelesenen Teil besonders im Kopf geblieben?",
        "spanish": "¿Qué se te ha quedado en la cabeza de lo que has leído?",
    }.get(language, "What has stayed with you in the part you’ve read?")
