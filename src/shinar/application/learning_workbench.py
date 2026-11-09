from __future__ import annotations

import json
import re
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from time import perf_counter
from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

from shinar.core.domain import (
    LearningMaterial,
    PracticeSession,
    ReviewItem,
    ReviewOutcome,
    ReviewRating,
    ReviewStatus,
    SessionUserProfile,
    SessionStatus,
    SessionSummary,
    PracticeOptions,
    new_id,
    Message,
    MessageRole,
    utc_now,
)
from shinar.core.conversation import ConversationTurn, ConversationRepository, with_interruption_notice, with_delivery_notice
from shinar.kernel.conversation_store import MemoryConversationRepository
from shinar.core.ports import EventStore, LearningLLMProvider
from shinar.kernel import (
    DirectLearningSessionRunner,
    SessionStepResult,
)
from shinar.infrastructure import SQLiteStore
from shinar.core.preparation_validation import validate_prepared_topic
from shinar.core.reading_scope import scope_material, reading_end
from shinar.application.source_index import build_source_index
from shinar.application.semantic_preparation import SemanticPreparation, analysis_with_knowledge
from shinar.core.knowledge_context import assemble_turn_context, digest, estimate_tokens, prime_turn_index
from shinar.core.knowledge import TurnSourceSnapshot
from shinar.core.source_reference import freeze_source_context
from shinar.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from shinar.core.knowledge_context import install_turn_index


from shinar.application.workbench_materials import MaterialWorkbench

class LearningWorkbench(MaterialWorkbench):
    """Thin application service for one text-learning session."""

    @property
    def provider(self) -> LearningLLMProvider:
        return self._provider

    @property
    def storage_path(self) -> Path | None:
        return getattr(self._event_store, "path", None)

    def __init__(
        self,
        provider: LearningLLMProvider,
        *,
        event_store: EventStore | None = None,
        conversation_repository: ConversationRepository | None = None,
    ) -> None:
        self._provider = provider
        self._event_store = event_store or SQLiteStore()
        self._turns = conversation_repository or (
            self._event_store if hasattr(self._event_store, "confirm_turn")
            else MemoryConversationRepository()
        )
        self._reply_task: asyncio.Task | None = None
        self._operation_owner: str | None = None
        self._operation_context: ContextVar[str | None] = ContextVar("conversation_owner", default=None)
        self._runner = DirectLearningSessionRunner(provider, self._event_store)
        self._material: LearningMaterial | None = None
        self._profile: SessionUserProfile | None = None
        self._session: PracticeSession | None = None
        self._materials: list[LearningMaterial] = []
        self._review_items: list[ReviewItem] = []
        self._preparation_task: asyncio.Task | None = None
        self._preparation_tasks: set[asyncio.Task] = set()
        self._preparation_lock = asyncio.Lock()
        self._preparation_status = "idle"
        self._preparation_calls = 0
        self._generation = 0
        self._sending = False
        self._semantic = SemanticPreparation(provider, self._event_store, foreground_active=lambda: self._sending)
        self._material_tasks: dict[str, asyncio.Task] = {}
        self._material_revisions: dict[str, int] = {}
        self.is_analyzing = False
        self._hydrate()

    @property
    def material(self) -> LearningMaterial | None:
        return self._material

    @property
    def profile(self) -> SessionUserProfile | None:
        return self._profile

    @property
    def session(self) -> PracticeSession | None:
        return self._session

    @property
    def preparation_status(self) -> str:
        return self._preparation_status


    @property
    def preparation_diagnostics(self) -> list[dict[str, Any]]:
        return list(getattr(self._provider, "preparation_diagnostics", []))

    @property
    def materials(self) -> list[LearningMaterial]:
        return list(self._materials)

    @property
    def review_queue(self) -> list[ReviewItem]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_review_items()
        return list(self._review_items)

    @property
    def due_review_items(self) -> list[ReviewItem]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_review_items(due_only=True)
        now = datetime.now(timezone.utc)
        return [
            item for item in self._review_items
            if item.status is ReviewStatus.ACTIVE and (item.due_at is None or item.due_at <= now)
        ]

    @property
    def due_review_count(self) -> int:
        return len(self.due_review_items)


    def list_sessions(self, material_id: str | None = None) -> list[PracticeSession]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_sessions(material_id=material_id)
        return [self._session] if self._session and (
            material_id is None or self._session.material_id == material_id) else []

    def list_session_summaries(self, material_id: str | None = None) -> list[SessionSummary]:
        summaries = self._event_store.list_session_summaries(material_id) if isinstance(
            self._event_store, SQLiteStore) else []
        current = self._session
        if current and (material_id is None or current.material_id == material_id):
            summaries = [SessionSummary.from_session(current),
                         *(item for item in summaries if item.id != current.id)]
        return summaries


    def select_material(self, material_id: str) -> LearningMaterial:
        self._require_idle_conversation()
        material = next((item for item in self._materials if item.id == material_id), None)
        if material is None:
            raise ValueError(f"Material not found: {material_id}")
        self._cancel_preparation()
        self._material = material
        sessions = self._stored_sessions_for(material.id)
        self._session = _runtime_session(sessions[0]) if sessions else None
        if self._session is not None:
            self._profile = self._session.profile
        else:
            self._profile = material.profile
        return material

    @property
    def sessions(self) -> list[PracticeSession]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_sessions(material_id=self._material.id if self._material else None)
        return [self._session] if self._session else []

    def select_session(self, session_id: str) -> PracticeSession:
        self._require_idle_conversation()
        if not isinstance(self._event_store, SQLiteStore):
            raise ValueError('本地历史记录不可用。')
        session = self._event_store.get_session(session_id)
        if session is None:
            raise ValueError('找不到这次对话，请刷新历史列表。')
        material = self._event_store.get_material(session.material_id)
        if material is None:
            raise ValueError('这次对话对应的材料已不存在。')
        self._cancel_preparation()
        self._session = _runtime_session(session)
        self._material = material
        self._profile = session.profile
        return self._session

    async def start_session(self, *, topic_id: str | None = None,
                            custom_topic: str | None = None,
                            options: PracticeOptions | None = None,
                            profile: SessionUserProfile | None = None,
                            material_id: str | None = None,
                            new_thread: bool = False) -> SessionStepResult:
        self._require_idle_conversation()
        previous = self._material, self._session, self._profile
        try:
            return await self._start_session(topic_id=topic_id, custom_topic=custom_topic,
                options=options, profile=profile, material_id=material_id, new_thread=new_thread)
        except Exception:
            self._material, self._session, self._profile = previous
            raise

    async def _start_session(self, *, topic_id: str | None = None,
                            custom_topic: str | None = None,
                            options: PracticeOptions | None = None,
                            profile: SessionUserProfile | None = None,
                            material_id: str | None = None,
                            new_thread: bool = False) -> SessionStepResult:
        if self._sending:
            raise RuntimeError("上一条消息仍在生成，请稍候。")
        if material_id is not None:
            material = self.get_material(material_id)
            if material is None:
                raise ValueError("找不到材料。")
            if not new_thread and self._session and self._session.status is SessionStatus.ACTIVE:
                raise RuntimeError("请先结束当前对话。")
            self._material = material
            self._profile = material.profile
        if new_thread:
            if self._session:
                self._save_session(self._session)
            self._cancel_preparation()
            self._session = None
        if self._material is None:
            raise RuntimeError("Load a material before starting a session.")
        if reading_end(self._material) == 0:
            raise ValueError("请先确认已读到哪里。")
        if self._material.analysis is None:
            self._material = self._material.model_copy(update={"analysis": build_source_index(self._material)})
            self._upsert_material(self._material)
        selected_profile = profile or self._profile
        if selected_profile is None:
            raise RuntimeError("Set a profile before starting a session.")

        if self._session is not None and self._session.status is SessionStatus.ACTIVE:
            raise RuntimeError("请先结束当前对话，再开始新的话题。")
        visible_material = scope_material(self._material)
        if self._uses_semantic():
            if len(visible_material.content) > 100000:
                index = await run_blocking(BlockingRequest("index", (visible_material,)))
                install_turn_index(index)
            else:
                prime_turn_index(visible_material)
        topics = visible_material.analysis.topics if visible_material.analysis else []
        topic = None
        initial_focus = custom_topic.strip() if custom_topic else ""
        if custom_topic and custom_topic.strip() and not self._uses_semantic():
            if len(custom_topic.strip()) > 500:
                raise ValueError("自定义话题最多 500 字符，请简要描述想聊什么。")
            topic = await self._provider.prepare_custom_topic(material=visible_material, title=custom_topic.strip(),
                target_language=selected_profile.target_language, native_language=selected_profile.native_language)
            topic = validate_prepared_topic(topic, visible_material.content)
            if self._material.analysis:
                analysis = self._material.analysis.model_copy(update={"topics": [*topics, topic]})
                self._material = self._material.model_copy(update={"analysis": analysis})
                self._upsert_material(self._material)
        elif topic_id:
            topic = next((item for item in topics if item.id == topic_id), None)
            if topic is None:
                raise ValueError("所选话题已失效，请重新选择。")
        selected_options = (options or PracticeOptions()).model_copy(update={"read_through": reading_end(self._material)})
        # Custom topics and a changed target language need a fresh opening;
        # the topic title itself may be in the learner's native language.
        if selected_options.mode.value == "discussion" and (
            topic is not None and not custom_topic and self._material.profile and
            self._material.profile.target_language is not selected_profile.target_language
        ):
            opening = await self._provider.generate_task(
                material=visible_material, learner_level=selected_profile.profile_level,
                target_language=selected_profile.target_language, topic=topic, options=selected_options,
            )
            topic = topic.model_copy(update={"opening_question": opening})
        result = await self._runner.start_session(
            material=visible_material,
            profile=selected_profile,
            topic=topic,
            options=selected_options,
        )
        self._session = result.session
        if initial_focus and self._uses_semantic():
            self._session = self._session.model_copy(update={"initial_focus": initial_focus[:500]})
            result = result.model_copy(update={"session": self._session})
        self._profile = result.session.profile
        self._save_session(self._session)
        self._preparation_calls = 0
        self._schedule_preparation()
        return result

    async def send_message(self, user_content: str, *, on_delta: Callable[[str], None] | None = None,
                           source_context: TurnSourceSnapshot | None = None,
                           request_id: str | None = None) -> SessionStepResult:
        # Legacy callers retry by resending the same composer text, without an ID.
        if request_id is None and self._session and self._session.messages:
            last = self._session.messages[-1]
            existing_id = last.metadata.get("turn_id") if last.role is MessageRole.USER else None
            if existing_id and last.content == user_content.strip() and last.source_context == source_context:
                return await self.generate_reply(existing_id, on_delta=on_delta)
        turn = self.confirm_user_input(user_content, request_id=request_id or new_id("request"),
                                       source_context=source_context)
        return await self.generate_reply(turn.id, on_delta=on_delta)

    @contextmanager
    def conversation_operation(self) -> Iterator[None]:
        if self._sending or self._operation_owner is not None:
            raise RuntimeError("conversation_busy")
        owner = new_id("operation")
        self._operation_owner = owner
        token = self._operation_context.set(owner)
        try:
            yield
        finally:
            self._operation_context.reset(token)
            self._operation_owner = None

    def _ensure_conversation_access(self) -> None:
        if self._operation_owner is not None and self._operation_context.get() != self._operation_owner:
            raise RuntimeError("conversation_busy")

    def _require_idle_conversation(self) -> None:
        if self._sending:
            raise RuntimeError("上一条消息仍在生成，请稍候。")
        if self._operation_owner is not None:
            raise RuntimeError("conversation_busy")

    def get_turn(self, turn_id: str) -> ConversationTurn:
        turn = self._turns.get_turn(turn_id)
        if not turn or not self._session or turn.session_id != self._session.id:
            raise ValueError("conversation_turn_missing")
        return turn

    def interrupt_reply(self, turn_id: str, reason: str) -> ConversationTurn:
        """Invalidate persistence before cancelling the producer (same worker loop)."""
        self.get_turn(turn_id)
        turn = self._turns.cancel_turn(turn_id, reason)
        self._session = with_interruption_notice(self._session, turn)
        if getattr(self, "_reply_turn_id", None) == turn_id and self._reply_task:
            self._reply_task.cancel()
        return turn

    def record_speech_delivery(self, turn_id: str, state: str, segment: int = -1) -> None:
        turn = self.get_turn(turn_id)
        self._turns.record_delivery(turn_id, state, segment)
        self._session = with_delivery_notice(self._session, turn, state)

    def freeze_turn_source(self, source_context: TurnSourceSnapshot | None) -> TurnSourceSnapshot | None:
        if source_context is None:
            return None
        material = self._session_material()
        return freeze_source_context(source_context, material_id=material.id,
            text=self._material.content, read_through=reading_end(material))

    def confirm_user_input(self, user_content: str, *, request_id: str,
                           source_context: TurnSourceSnapshot | None = None,
                           confirmation_kind: str = "manual_text") -> ConversationTurn:
        self._ensure_conversation_access()
        if len(user_content) > 4000:
            raise ValueError("单条发言最多 4000 字符，请拆成几次发言。")
        if self._material is None:
            raise RuntimeError("Load a material before sending a message.")
        if self._session is None:
            raise RuntimeError("Start a session before sending a message.")
        if self._session.status is not SessionStatus.ACTIVE:
            raise RuntimeError("Start a new session before sending more messages.")
        if self._sending:
            raise RuntimeError("上一条消息仍在生成，请稍候。")
        if not request_id.strip() or len(request_id) > 200:
            raise ValueError("invalid_request_id")
        material = self._session_material()
        source_context = self.freeze_turn_source(source_context)
        previous = self._turns.find_turn(self._session.id, request_id)
        if previous:
            message = next((m for m in self._session.messages if m.id == previous.user_message_id), None)
            if not message or message.content != user_content.strip() or message.source_context != source_context:
                raise ValueError("request_id_content_mismatch")
            return previous
        context = assemble_turn_context(material, self._session, user_content,
            source_context=source_context) if self._uses_semantic() or source_context else None
        message = Message(role=MessageRole.USER, content=user_content, source_context=source_context,
                          metadata={"confirmation_kind": confirmation_kind,
                                    "previous_reply_interrupted": any(m.metadata.get("reply_interrupted") or m.metadata.get("speech_interrupted") for m in self._session.messages[-2:])})
        turn = ConversationTurn(session_id=self._session.id, request_id=request_id,
            user_message_id=message.id, history_ids=[m.id for m in self._session.messages],
            source_hash=digest(self._material.content), scope_end=reading_end(material),
            context=context, preparation=self._session.preparation)
        message = message.model_copy(update={"metadata": {**message.metadata, "turn_id": turn.id}})
        confirmed = self._session.model_copy(update={"messages": [*self._session.messages, message],
                                                      "updated_at": utc_now()})
        from shinar.kernel.session_runner import message_event
        # Confirmation is durable; generated fragments are not conversation history.
        committed = self._turns.confirm_turn(turn, confirmed, message_event(confirmed.id, message))
        if committed.id == turn.id:
            self._session = confirmed
        return committed

    async def generate_reply(self, turn_id: str, *, on_delta: Callable[[str], None] | None = None) -> SessionStepResult:
        self._ensure_conversation_access()
        turn = self.get_turn(turn_id)
        if turn.state == "completed":
            message = next(m for m in self._session.messages if m.id == turn.assistant_message_id)
            return SessionStepResult(session=self._session, assistant_message=message, turn_id=turn.id)
        if self._sending:
            raise RuntimeError("上一条消息仍在生成，请稍候。")
        if self._session.status is not SessionStatus.ACTIVE:
            raise RuntimeError("conversation_session_inactive")
        if self._session.messages[-1].id != turn.user_message_id:
            raise ValueError("conversation_turn_superseded")
        if digest(self._material.content) != turn.source_hash:
            raise ValueError("conversation_source_changed")
        user_message = self._session.messages[-1]
        before = self._session.model_copy(update={"messages": self._session.messages[:-1],
                                                 "preparation": turn.preparation})
        if [m.id for m in before.messages] != turn.history_ids:
            raise ValueError("conversation_history_changed")
        turn = self._turns.claim_turn(turn.id)
        self._sending = True
        self._reply_task = asyncio.current_task()
        self._reply_turn_id = turn.id
        if not self._uses_semantic():
            self._cancel_preparation()
        try:
            # The complete foreground attempt must end before its durable lease.
            async with asyncio.timeout(150):
                material = scope_material(self._material, turn.scope_end)
                user_content = user_message.content
                source_context = user_message.source_context
                context = turn.context
                if self._uses_semantic() and context and context.evidence and context.gaps and re.search(r"\b(check|verify|which chapter|what exactly)\b|核对|确认原文|確かめ", user_content, re.I):
                    started = perf_counter()
                    try:
                        focus = await self._semantic.focus(material, before, context, query=user_content, background=False)
                        context = context.model_copy(update={"focus_points": focus.points})
                    except Exception:
                        pass
                    context = context.model_copy(update={"verification_ms": (perf_counter() - started) * 1000})
                async def reply():
                    async with asyncio.timeout(150):
                        return await self._runner.handle_user_message(session=before, material=material,
                            user_content=user_content, on_delta=on_delta, turn_context=context,
                            source_context=source_context, confirmed_user=user_message, persist_events=False)
                if context and hasattr(self._event_store, "ensure_model_budget"):
                    owner = f"dialogue:{self._session.id}"
                    self._event_store.ensure_model_budget(owner, input_limit=10**12, output_limit=10**12, request_limit=100000)
                    result = await self._semantic.account(owner, "dialogue", turn.id,
                        estimate_tokens(context.model_dump_json()) + estimate_tokens(" ".join(m.content for m in self._session.messages[-10:])) + 1000,
                        getattr(self._provider, "dialogue_output_budget", 160), reply,
                        metadata={"source_hash": context.source_hash, "scope_end": context.scope_end,
                                  "session_revision": len(self._session.messages),
                                  "evidence_ids": [item.id for item in context.evidence]})
                else:
                    result = await reply()
                if self._session.id != turn.session_id:
                    raise RuntimeError("conversation_session_changed")
                # A successful explicit retry supersedes its earlier interruption notice.
                if any(m.id == turn.user_message_id and m.metadata.get("reply_interrupted") for m in result.session.messages):
                    messages = [m.model_copy(update={"metadata": {k: v for k, v in m.metadata.items() if k != "reply_interrupted"}})
                                if m.id == turn.user_message_id else m for m in result.session.messages]
                    result = result.model_copy(update={"session": result.session.model_copy(update={"messages": messages})})
                self._turns.finish_turn(turn, result.session, result.events)
                if self._turns is not self._event_store:
                    await self._event_store.append_many(result.events)
                self._session = result.session
                result = result.model_copy(update={"turn_id": turn.id})
        except BaseException as exc:
            self._turns.fail_turn(turn, "cancelled" if isinstance(exc, asyncio.CancelledError) else "reply_failed")
            raise
        finally:
            self._sending = False
            self._reply_task = None
            self._reply_turn_id = None
        self._schedule_preparation()
        return result

    def review_items(self) -> list[ReviewItem]:
        return self.review_queue

    async def complete_session(self) -> SessionStepResult:
        self._require_idle_conversation()
        if self._material is None or self._session is None:
            raise RuntimeError("Start a session before completing it.")
        self._cancel_preparation()
        async def finish():
            return await self._runner.complete_session(session=self._session, material=self._session_material())
        will_request_review = (self._session.status is SessionStatus.ACTIVE
            and any(message.role.value == "user" for message in self._session.messages)
            and (self._session.options is None or self._session.options.feedback_timing.value != "off"))
        if self._uses_semantic() and will_request_review and hasattr(self._event_store, "ensure_model_budget"):
            owner = f"review:{self._session.id}"
            self._event_store.ensure_model_budget(owner, input_limit=32000, output_limit=8192, request_limit=2)
            result = await self._semantic.account(owner, "review", new_id("review_call"),
                estimate_tokens(" ".join(message.content for message in self._session.messages[-40:])) + 1500,
                4096, finish)
        else:
            result = await finish()
        self._session = result.session
        self._review_items = [
            item for item in self._review_items
            if item.source_session_id != self._session.id
        ]
        self._review_items.extend(result.review_items)
        self._save_session(self._session)
        return result

    async def record_review_outcome(
        self, review_item_id: str, rating: ReviewRating, answer: str | None = None
    ) -> ReviewOutcome:
        item = next((candidate for candidate in self.review_queue if candidate.id == review_item_id), None)
        if item is None:
            raise ValueError(f"Review item not found: {review_item_id}")
        if rating in {ReviewRating.GOOD, ReviewRating.EASY} and not _review_answer_matches(
            submitted=answer,
            expected=item.answer,
        ):
            raise ValueError(
                "Review answer does not match the expected answer closely enough for good/easy. "
                "Use again or hard to record an incorrect attempt."
            )
        now = datetime.now(timezone.utc)
        intervals = {
            ReviewRating.AGAIN: timedelta(minutes=10),
            ReviewRating.HARD: timedelta(days=1),
            ReviewRating.GOOD: timedelta(days=3),
            ReviewRating.EASY: timedelta(days=7),
        }
        next_due = now + intervals[rating]
        status = ReviewStatus.MASTERED if rating is ReviewRating.EASY else ReviewStatus.ACTIVE
        updated = item.model_copy(update={"due_at": next_due, "status": status})
        outcome = ReviewOutcome(
            review_item_id=item.id,
            rating=rating,
            answer=answer,
            next_due_at=next_due,
        )
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_review_item(updated)
        else:
            self._review_items = [
                updated if candidate.id == updated.id else candidate
                for candidate in self._review_items
            ]
        await self._event_store.append(
            self._review_event(outcome, item.source_session_id or "review")
        )
        return outcome

    async def update_review_status(self, review_item_id: str, status: ReviewStatus) -> None:
        item = next((candidate for candidate in self.review_queue if candidate.id == review_item_id), None)
        if item is None:
            raise ValueError(f"Review item not found: {review_item_id}")
        updated = item.model_copy(update={"status": status})
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_review_item(updated)
        else:
            self._review_items = [
                updated if candidate.id == updated.id else candidate
                for candidate in self._review_items
            ]
        event_type = {
            ReviewStatus.PAUSED: "review.paused",
            ReviewStatus.IGNORED: "review.ignored",
            ReviewStatus.ARCHIVED: "review.archived",
            ReviewStatus.DELETED: "review.deleted",
        }.get(status)
        if event_type:
            from shinar.core.domain import SessionEvent, SessionEventType
            await self._event_store.append(
                SessionEvent(
                    session_id=item.source_session_id or "review",
                    event_type=SessionEventType(event_type),
                    payload={"review_item_id": item.id},
                )
            )

    async def export_json(self, path: Path) -> Path:
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        session_id = self._session.id if self._session is not None else None
        events = (
            await self._event_store.list_session_events(session_id)
            if session_id is not None
            else []
        )

        payload: dict[str, Any] = {
            "material": self._material.model_dump(mode="json") if self._material else None,
            "profile": self._profile.model_dump(mode="json") if self._profile else None,
            "session": self._session.model_dump(mode="json") if self._session else None,
            "events": [event.model_dump(mode="json") for event in events],
            "review_queue": [item.model_dump(mode="json") for item in self.review_queue],
        }

        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def reset(self) -> None:
        self._require_idle_conversation()
        self._cancel_preparation()
        self._material = None
        self._profile = None
        self._session = None
        self._review_items = self.review_queue

    def overview_lines(self) -> list[str]:
        lines: list[str] = []
        if self._material is None:
            return ["No material loaded."]

        lines.append(f"Material: {self._material.title}")
        lines.append(f"Source language: {self._material.source_language.value}")
        if self._profile is not None:
            lines.append(f"Target language: {self._profile.target_language.value}")
            lines.append(f"Learner level: {self._profile.profile_level.value}")
        if self._material.analysis is not None:
            lines.append(f"Summary: {self._material.analysis.summary}")
            if self._material.analysis.keywords:
                lines.append("Keywords: " + ", ".join(self._material.analysis.keywords))
            if self._material.analysis.suggested_goals:
                lines.append(
                    "Goals: " + "; ".join(self._material.analysis.suggested_goals)
                )
        return lines

    def session_lines(self) -> list[str]:
        if self._session is None:
            return ["No active session."]

        lines = [
            f"Session: {self._session.id}",
            f"Status: {self._session.status.value}",
            f"Messages: {len(self._session.messages)}",
            f"Feedback items: {len(self._session.feedback_items)}",
            f"Review items: {len(self._session.review_items)}",
        ]
        if self._session.completed_at is not None:
            lines.append(f"Completed at: {self._session.completed_at.isoformat()}")
        if self._session.status is SessionStatus.COMPLETED and self._session.review is not None:
            review = self._session.review
            lines.append(f"Review summary: {review.summary}")
            if review.focus_areas:
                lines.append("Focus: " + "; ".join(review.focus_areas[:3]))
            if review.next_action:
                lines.append(f"Next action: {review.next_action}")
        elif self._session.current_instruction is not None:
            lines.append("Current task:")
            lines.append(self._session.current_instruction.prompt)
        if self._session.status is SessionStatus.COMPLETED and self._session.current_instruction is not None:
            lines.append("Historical task:")
            lines.append(self._session.current_instruction.prompt)
        if self._session.messages:
            last_message = self._session.messages[-1]
            lines.append(f"Last message [{last_message.role.value}]: {last_message.content}")
        return lines

    def review_lines(self, *, due_only: bool = True) -> list[str]:
        all_items = self.review_queue
        items = self.due_review_items if due_only else all_items
        if not items:
            if due_only and all_items:
                return [
                    f"今日到期复习项（0 项；全部复习项 {len(all_items)} 项，可用 review --all 查看）。"
                ]
            return ["今日到期复习项（0 项）。" if due_only else "全部复习项（0 项）。"]

        if due_only:
            lines = [
                f"今日到期复习项（{len(items)} 项；全部复习项 {len(all_items)} 项，可用 review --all 查看）："
            ]
        else:
            lines = [f"全部复习项（{len(items)} 项；今日到期 {self.due_review_count} 项）："]
        for index, item in enumerate(items, start=1):
            due = item.due_at.isoformat() if item.due_at is not None else "now"
            lines.append(f"{index}. {item.prompt} (due: {due})")
        return lines

    def _hydrate(self) -> None:
        if not isinstance(self._event_store, SQLiteStore):
            return
        self._materials = self._event_store.list_materials()
        for index, material in enumerate(self._materials):
            knowledge = material.analysis.knowledge if material.analysis else None
            if knowledge and knowledge.status == "preparing":
                # A previous process cannot leave a permanent preparing state.
                knowledge = knowledge.model_copy(update={"status": "partial"})
                material = material.model_copy(update={"analysis": analysis_with_knowledge(material.analysis, knowledge)})
                self._materials[index] = material
                self._event_store.save_material(material)
            if knowledge and knowledge.brief and any(not set(point.support_ids) <= {note.id for note in knowledge.notes} for point in knowledge.brief.points):
                # Recover a development/older manifest without inventing evidence.
                # Explicit resume can rebuild its manifest from cached merges.
                knowledge = knowledge.model_copy(update={"status": "partial", "brief": None,
                    "errors": {**knowledge.errors, "brief": "UnresolvedProvenance"}})
                material = material.model_copy(update={"analysis": analysis_with_knowledge(material.analysis, knowledge)})
                self._materials[index] = material
                self._event_store.save_material(material)
            if knowledge:
                self._semantic.save_manifest(material, knowledge)
        self._review_items = self._event_store.list_review_items()
        sessions = self._event_store.list_sessions(limit=1)
        if sessions:
            latest = sessions[0]
            self._session = _runtime_session(latest)
            self._material = self._event_store.get_material(latest.material_id)
            self._profile = latest.profile
        elif self._materials:
            self._material = self._materials[0]
            self._profile = self._material.profile

    async def aclose(self) -> None:
        self._cancel_preparation()
        tasks = [*self._material_tasks.values(), *self._preparation_tasks]
        if self._reply_task:
            tasks.append(self._reply_task)
        pending = []
        for task in set(tasks) - {asyncio.current_task()}:
            if task.done():
                # Completed seed tasks can belong to an already closed loop.
                # Read their outcome without attaching new callbacks to that loop.
                if not task.cancelled():
                    task.exception()
            else:
                task.cancel()
                pending.append(task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close = getattr(self._provider, "aclose", None)
        if close:
            await close()
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.close()


    def _save_session(self, session: PracticeSession) -> None:
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_session(session)

    def _stored_sessions_for(self, material_id: str) -> list[PracticeSession]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_sessions(material_id=material_id)
        return []

    @staticmethod
    def _review_event(outcome: ReviewOutcome, session_id: str):
        from shinar.core.domain import SessionEvent, SessionEventType
        return SessionEvent(
            session_id=session_id,
            event_type=SessionEventType.REVIEW_OUTCOME_RECORDED,
            payload=outcome.model_dump(mode="json"),
        )


def _review_answer_matches(*, submitted: str | None, expected: str) -> bool:
    submitted_text = _normalize_review_answer(submitted or "")
    expected_text = _normalize_review_answer(expected)
    if not submitted_text or not expected_text:
        return False
    return (
        submitted_text == expected_text
        or expected_text in submitted_text
        or submitted_text in expected_text
    )


def _runtime_session(session: PracticeSession) -> PracticeSession:
    """Upgrade only future behaviour of old active sessions; historical messages stay intact."""
    if session.options is None and session.status is SessionStatus.ACTIVE:
        return session.model_copy(update={"options": PracticeOptions(difficulty=session.profile.profile_level)})
    return session


def _normalize_review_answer(value: str) -> str:
    text = value.casefold().strip()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
