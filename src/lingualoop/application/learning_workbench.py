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

from lingualoop.core.domain import (
    LanguageEnum,
    LearningMaterial,
    MaterialTrack,
    MaterialSourceType,
    NormalizationStatus,
    PracticeSession,
    ProficiencyLevel,
    ReviewItem,
    ReviewOutcome,
    ReviewRating,
    ReviewStatus,
    SessionUserProfile,
    SessionStatus,
    DiscussionTopic,
    PracticeOptions,
    SubtitleCue,
    new_id,
    Message,
    MessageRole,
    utc_now,
)
from lingualoop.core.conversation import ConversationTurn, ConversationRepository
from lingualoop.kernel.conversation_store import MemoryConversationRepository
from lingualoop.core.ports import EventStore, LearningLLMProvider
from lingualoop.kernel import (
    DirectLearningSessionRunner,
    SessionStepResult,
)
from lingualoop.infrastructure import SQLiteStore
from lingualoop.infrastructure.material_import import ImportedMaterial
from lingualoop.application.material_preparation import prepare_material, MAX_TOPICS, preparation_cache_key
from lingualoop.core.preparation_validation import validate_dialogue_preparation, validate_prepared_topic
from lingualoop.core.reading_scope import scope_material, reading_end
from lingualoop.core.material_context import dialogue_knowledge
from lingualoop.application.source_index import build_source_index
from lingualoop.application.semantic_preparation import SemanticPreparation, analysis_with_knowledge
from lingualoop.core.knowledge_context import assemble_turn_context, digest, estimate_tokens, prime_turn_index
from lingualoop.core.knowledge import TurnSourceSnapshot
from lingualoop.core.source_reference import freeze_source_context


class LearningWorkbench:
    """Thin application service for one text-learning session."""

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

    def _uses_semantic(self) -> bool:
        return self._semantic.supported and bool(getattr(self._provider, "supports_free_chat", False)
            or (self._material and self._material.analysis and self._material.analysis.knowledge))

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

    async def load_material(
        self,
        *,
        title: str,
        source_language: LanguageEnum,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
        learner_level: ProficiencyLevel,
        content: str,
        source_type: MaterialSourceType = MaterialSourceType.TEXT,
        raw_content: str | None = None,
        normalized_content: str | None = None,
        source_path: str | None = None,
        track: MaterialTrack = MaterialTrack.ARTICLE_READING,
        subtitle_cues: list[SubtitleCue] | None = None,
        auto_prepare: bool = True,
        source_sections: list | None = None,
    ) -> LearningMaterial:
        self._require_idle_conversation()
        draft = LearningMaterial(
            title=title,
            source_language=source_language,
            content=normalized_content or content,
            source_type=source_type,
            raw_content=raw_content or content,
            normalized_content=normalized_content or content,
            source_hash=digest(normalized_content or content),
            source_path=source_path,
            source_sections=source_sections or [],
            track=track,
            normalization_status=NormalizationStatus.NORMALIZED,
            subtitle_cues=subtitle_cues or [],
            read_through=None if auto_prepare else 0,
            profile=SessionUserProfile(profile_level=learner_level, native_language=native_language,
                                       target_language=target_language),
        )
        same = next((item for item in self._materials if item.title == draft.title and item.content == draft.content
                     and item.profile == draft.profile and item.source_language == draft.source_language), None)
        if same:
            if getattr(self._provider, 'offline_read_only', False) or (same.analysis and same.analysis.preparation_complete):
                return self.select_material(same.id)
            draft = draft.model_copy(update={'id': same.id, 'created_at': same.created_at,
                'analysis': same.analysis, 'analysis_cache_key': same.analysis_cache_key,
                'read_through': same.read_through, 'full_analysis_cache_key': same.full_analysis_cache_key})
        source_hash, cache_key = preparation_cache_key(self._provider, draft, draft.profile)
        cached = self._event_store.get_preparation_cache(cache_key) if isinstance(self._event_store, SQLiteStore) else None
        # The material may also contain custom topics added after canonical preparation.
        if same and same.analysis_cache_key == cache_key and same.analysis and same.analysis.preparation_complete:
            cached = same.analysis
        if cached:
            draft = draft.model_copy(update={'analysis': cached, 'analysis_cache_key': cache_key})
        self._material = draft
        self._cancel_preparation()
        self._profile = draft.profile
        self._session = None
        self._upsert_material(draft)
        if cached:
            self.select_material(draft.id)
            return self._material
        if not auto_prepare:
            return draft
        return await self.analyze_current_material()

    async def analyze_current_material(self, *, profile: SessionUserProfile | None = None) -> LearningMaterial:
        self._require_idle_conversation()
        if getattr(self._provider, 'offline_read_only', False):
            raise RuntimeError('AI 服务尚未配置，本地整理资料会保留。请配置 .env 后重启再继续整理。')
        if profile is not None and self._material is not None:
            old_profile = self._material.profile
            self._profile = profile
            keep_analysis = old_profile == profile or bool(self._material.analysis and self._material.analysis.knowledge)
            self._material = self._material.model_copy(update={"profile": profile,
                "analysis": self._material.analysis if keep_analysis else None,
                "full_analysis_cache_key": self._material.full_analysis_cache_key if keep_analysis else None})
            self._upsert_material(self._material)
        if self._material is None or self._profile is None:
            raise RuntimeError("请先选择材料并设置语言。")
        if self._semantic.supported and getattr(self._provider, "supports_free_chat", False):
            return await self.prepare_current_material()
        if (self._material.analysis and self._material.analysis_cache_key
                and reading_end(self._material) == len(self._material.content)):
            self._material = self._material.model_copy(update={"full_analysis_cache_key": self._material.analysis_cache_key})
        source_hash, cache_key = preparation_cache_key(self._provider, self._material, self._profile)
        if self._material.analysis_cache_key != cache_key:
            cached = self._event_store.get_preparation_cache(cache_key) if isinstance(self._event_store, SQLiteStore) else None
            prior = self._material.analysis if self._material.analysis_cache_key is None else None
            self._material = self._material.model_copy(update={'analysis': cached or prior, 'analysis_cache_key': cache_key})
        self._cancel_preparation()
        async def persist_progress(analysis):
            self._material = self._material.model_copy(update={"analysis": analysis})
            self._upsert_material(self._material)
            if isinstance(self._event_store, SQLiteStore):
                self._event_store.save_preparation_cache(cache_key, source_hash, analysis)
        self.is_analyzing = True
        try:
            analysis = await prepare_material(self._provider, self._material, self._profile, persist_progress)
        finally:
            self.is_analyzing = False
        self._material = self._material.model_copy(update={"analysis": analysis})
        self._upsert_material(self._material)
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_preparation_cache(cache_key, source_hash, analysis)
        return self._material

    async def load_imported_material(
        self,
        imported: ImportedMaterial,
        *,
        title: str | None = None,
        source_language: LanguageEnum,
        target_language: LanguageEnum,
        native_language: LanguageEnum,
        learner_level: ProficiencyLevel,
        track: MaterialTrack = MaterialTrack.ARTICLE_READING,
        auto_prepare: bool = True,
    ) -> LearningMaterial:
        self._require_idle_conversation()
        return await self.load_material(
            title=title or imported.title,
            source_language=source_language,
            target_language=target_language,
            native_language=native_language,
            learner_level=learner_level,
            content=imported.normalized_content,
            source_type=imported.source_type,
            raw_content=imported.raw_content,
            normalized_content=imported.normalized_content,
            source_path=imported.source_path,
            track=track,
            subtitle_cues=imported.subtitle_cues,
            source_sections=imported.source_sections,
            auto_prepare=auto_prepare,
        )

    def get_material(self, material_id: str) -> LearningMaterial | None:
        return next((item for item in self._materials if item.id == material_id), None)

    def list_sessions(self, material_id: str | None = None) -> list[PracticeSession]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_sessions(material_id=material_id)
        return [self._session] if self._session and (
            material_id is None or self._session.material_id == material_id) else []

    async def store_imported_material(self, imported: ImportedMaterial, **kwargs: Any) -> LearningMaterial:
        """Save an import without replacing the foreground conversation."""
        previous = self._material, self._session, self._profile
        try:
            return await self.load_imported_material(imported, auto_prepare=False, **kwargs)
        finally:
            self._material, self._session, self._profile = previous

    def set_reading_scope(self, end: int, *, material_id: str | None = None) -> LearningMaterial:
        self._require_idle_conversation()
        if material_id is not None:
            material = self.get_material(material_id)
            if material is None:
                raise ValueError("找不到材料。")
            previous = self._material, self._session, self._profile
            try:
                self._material, self._session, self._profile = material, None, material.profile
                return self.set_reading_scope(end)
            finally:
                prior_material, self._session, self._profile = previous
                self._material = self.get_material(prior_material.id) if prior_material else None
        material = self._material
        if material is None:
            raise ValueError("请先导入材料。")
        if self._session and self._session.status is SessionStatus.ACTIVE:
            raise ValueError("请先结束当前对话，再更改阅读范围。")
        if not 0 < end <= len(material.content):
            raise ValueError("阅读范围必须落在已导入的原文内。")
        knowledge = material.analysis.knowledge if material.analysis else None
        if knowledge and self._semantic.supported:
            task = self._material_tasks.get(material.id)
            if (knowledge.scope_end == end and knowledge.generation_identity == self._semantic.identity(material)
                and (knowledge.status == "ready" or (task and not task.done()))):
                return material
            self._cancel_preparation()
            updated = material.model_copy(update={"read_through": end})
            if task and not task.done():
                task.get_loop().call_soon_threadsafe(task.cancel)
            self._material_revisions[material.id] = self._material_revisions.get(material.id, 0) + 1
            cached_knowledge = self._semantic.load_manifest(updated, end, knowledge.generation_identity)
            if cached_knowledge and cached_knowledge.status == "ready":
                self._material = updated.model_copy(update={"analysis": analysis_with_knowledge(updated.analysis, cached_knowledge)})
                self._upsert_material(self._material)
                return self._material
            self._material = updated.model_copy(update={"analysis": analysis_with_knowledge(
                updated.analysis, self._semantic.initial(updated))})
            self._upsert_material(self._material)
            try:
                self._begin_material_preparation(self._material)
            except RuntimeError:
                pass
            return self._material
        self._cancel_preparation()
        # Keep paid-for full-book preparation in its original cache.
        digest, prior_key = preparation_cache_key(self._provider, material, material.profile or self._profile)
        prior_key = material.analysis_cache_key or prior_key
        full_key = material.full_analysis_cache_key
        if material.analysis and isinstance(self._event_store, SQLiteStore):
            self._event_store.save_preparation_cache(prior_key, digest, material.analysis)
            if reading_end(material) == len(material.content):
                full_key = prior_key
        updated = material.model_copy(update={"read_through": end, "full_analysis_cache_key": full_key})
        _, key = preparation_cache_key(self._provider, updated, updated.profile or self._profile)
        cached = self._event_store.get_preparation_cache(key) if isinstance(self._event_store, SQLiteStore) else None
        if not cached and end == len(material.content) and full_key and isinstance(self._event_store, SQLiteStore):
            cached = self._event_store.get_preparation_cache(full_key)
        # Reuse the source index without asking a model to summarize the unread book.
        analysis = cached or build_source_index(updated)
        self._material = updated.model_copy(update={"analysis": analysis, "analysis_cache_key": key})
        self._upsert_material(self._material)
        if isinstance(self._event_store, SQLiteStore):
            digest, _ = preparation_cache_key(self._provider, self._material, self._material.profile or self._profile)
            self._event_store.save_preparation_cache(key, digest, analysis)
        if self._semantic.supported:
            existing = self._material.analysis.knowledge if self._material.analysis else None
            if not existing or existing.scope_end != end or existing.status != "ready":
                initial = self._semantic.initial(self._material)
                self._material = self._material.model_copy(update={"analysis": analysis_with_knowledge(self._material.analysis, initial)})
                self._upsert_material(self._material)
                try:
                    self._begin_material_preparation(self._material)
                except RuntimeError:
                    # Synchronous callers can explicitly await prepare_current_material.
                    pass
        return self._material

    def _begin_material_preparation(self, material: LearningMaterial) -> asyncio.Task:
        loop = asyncio.get_running_loop()
        revision = self._material_revisions.get(material.id, 0) + 1
        self._material_revisions[material.id] = revision
        old = self._material_tasks.get(material.id)
        if old and not old.done():
            old.cancel()

        async def prepare():
            async def progress(knowledge):
                current = next((item for item in self._materials if item.id == material.id), None)
                if (current is None or reading_end(current) != reading_end(material)
                    or self._material_revisions.get(material.id) != revision
                    or (current.source_hash or digest(current.content)) != (material.source_hash or digest(material.content))):
                    return
                updated = current.model_copy(update={"analysis": analysis_with_knowledge(
                    current.analysis or build_source_index(current), knowledge)})
                previous_knowledge = current.analysis.knowledge if current.analysis else None
                if previous_knowledge:
                    units = {unit.id for unit in knowledge.units}
                    spans = {span.id for unit in knowledge.units for span in unit.paragraphs}
                    facts = [note for note in previous_knowledge.notes if note.id.startswith("focus_")
                        and note.knowledge_end <= knowledge.scope_end and note.unit_id in units
                        and set(note.dependency_ids) <= units and set(note.support_ids) <= spans]
                    if facts:
                        combined = {note.id: note for note in [*knowledge.notes, *facts]}
                        knowledge = knowledge.model_copy(update={"notes": list(combined.values())})
                        updated = current.model_copy(update={"analysis": analysis_with_knowledge(current.analysis, knowledge)})
                self._semantic.save_manifest(updated, knowledge)
                self._materials = [updated if item.id == updated.id else item for item in self._materials]
                if isinstance(self._event_store, SQLiteStore):
                    self._event_store.save_material(updated)
                if self._material and self._material.id == updated.id:
                    self._material = updated
            return await self._semantic.prepare(material, progress)

        task = loop.create_task(prepare(), name=f"material-understanding-{material.id}")
        self._material_tasks[material.id] = task
        return task

    def resume_material_preparation(self) -> LearningMaterial:
        if not self._semantic.supported or not self._material or reading_end(self._material) == 0:
            raise ValueError("请先确认已读范围并配置推理服务。")
        task = self._material_tasks.get(self._material.id)
        if task is None or task.done():
            self._begin_material_preparation(self._material)
        return self._material

    async def prepare_current_material(self) -> LearningMaterial:
        if self._material is None or reading_end(self._material) == 0:
            raise ValueError("请先确认已读范围。")
        material = self._material
        task = self._material_tasks.get(material.id)
        if task is None or task.done():
            task = self._begin_material_preparation(material)
        await task
        return next(item for item in self._materials if item.id == material.id)

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
            await asyncio.to_thread(prime_turn_index, visible_material)
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
                          metadata={"confirmation_kind": confirmation_kind})
        turn = ConversationTurn(session_id=self._session.id, request_id=request_id,
            user_message_id=message.id, history_ids=[m.id for m in self._session.messages],
            source_hash=digest(self._material.content), scope_end=reading_end(material),
            context=context, preparation=self._session.preparation)
        message = message.model_copy(update={"metadata": {**message.metadata, "turn_id": turn.id}})
        confirmed = self._session.model_copy(update={"messages": [*self._session.messages, message],
                                                      "updated_at": utc_now()})
        from lingualoop.kernel.session_runner import message_event
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
            from lingualoop.core.domain import SessionEvent, SessionEventType
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
        sessions = self._event_store.list_sessions()
        if sessions:
            latest = sessions[0]
            self._session = _runtime_session(latest)
            self._material = self._event_store.get_material(latest.material_id)
            self._profile = latest.profile
        elif self._materials:
            self._material = self._materials[0]
            self._profile = self._material.profile

    async def aclose(self) -> None:
        if self._reply_task and self._reply_task is not asyncio.current_task():
            self._reply_task.cancel()
            await asyncio.gather(self._reply_task, return_exceptions=True)
        self._cancel_preparation()
        tasks = list(self._material_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._preparation_tasks:
            await asyncio.gather(*self._preparation_tasks, return_exceptions=True)
        close = getattr(self._provider, "aclose", None)
        if close:
            await close()
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.close()

    def _session_material(self) -> LearningMaterial:
        end = self._session.options.read_through if self._session and self._session.options else None
        material = self._material
        knowledge = material.analysis.knowledge if material and material.analysis else None
        if knowledge and end is not None and knowledge.scope_end != end:
            cached = self._semantic.load_manifest(material, end, knowledge.generation_identity)
            if cached:
                material = material.model_copy(update={"analysis": analysis_with_knowledge(material.analysis, cached)})
        return scope_material(material, end)

    def _cancel_preparation(self) -> None:
        self._generation += 1
        task = self._preparation_task
        self._preparation_task = None
        self._preparation_status = "idle"
        if task and not task.done():
            task.get_loop().call_soon_threadsafe(task.cancel)

    def _schedule_preparation(self) -> None:
        if self._uses_semantic():
            self._schedule_semantic_reference()
            return
        session = self._session
        material = self._session_material() if session and self._material else self._material
        prepare = getattr(self._provider, "prepare_dialogue", None)
        if not session or not material or prepare is None or self._preparation_calls >= 12:
            return
        if session.topic is None:
            # Let the real conversation establish interests. Refresh only for a new
            # source selection, with a persisted cap that also survives app restarts.
            users = [message for message in session.messages if message.role.value == "user"]
            if len(users) < 2 or session.reference_refresh_count >= 3:
                return
            refs = dialogue_knowledge(material, users[-1].content)
            key = "|".join(sorted({str(item.get("section", "")) for item in refs}))
            if not key or key == session.reference_source_key:
                return
            session = session.model_copy(update={"reference_refresh_count": session.reference_refresh_count + 1,
                                                 "reference_source_key": key})
            self._session = session
            self._save_session(session)
        self._preparation_calls += 1
        generation = self._generation
        revision = len(session.messages)
        self._preparation_status = "preparing"

        async def run():
            try:
                async with self._preparation_lock:
                    if generation != self._generation:
                        return
                    prepared = await asyncio.wait_for(prepare(material=material, session=session), timeout=45)
                if (generation != self._generation or not self._session or
                    self._session.id != session.id or len(self._session.messages) != revision or
                    self._session.status is not SessionStatus.ACTIVE):
                    return
                if prepared.based_on_message_count != revision:
                    return
                prepared = validate_dialogue_preparation(prepared, material.content)
                self._session = self._session.model_copy(update={"preparation": prepared})
                self._save_session(self._session)
                self._preparation_status = "ready"
            except asyncio.CancelledError:
                pass
            except Exception:
                if generation == self._generation:
                    self._preparation_status = "unavailable"

        task = asyncio.create_task(run(), name=f"prepare-{session.id}-{revision}")
        self._preparation_task = task
        self._preparation_tasks.add(task)
        task.add_done_callback(self._preparation_tasks.discard)

    def _schedule_semantic_reference(self) -> None:
        session = self._session
        if not session or session.status is not SessionStatus.ACTIVE or not self._material:
            return
        users = [message for message in session.messages if message.role.value == "user"]
        if not users or re.search(r"\b(let.s (?:stop|leave)|leave it (?:there|here|today)|stop (?:there|here|for now)|goodbye|thanks.*bye|that.s all)\b|先到这|不聊了|またね", users[-1].content, re.I):
            return
        if self._preparation_task and not self._preparation_task.done():
            return
        material = self._session_material()
        context = assemble_turn_context(material, session, users[-1].content)
        if not context.gaps or (not context.evidence and "memory" not in context.gaps):
            return
        if (session.focus_reference and session.focus_reference.key == context.focus_key
            and users[-1].id in session.focus_reference.based_on_message_ids and "memory" not in context.gaps):
            return
        generation = self._generation
        revision = len(session.messages)
        self._preparation_status = "preparing"
        async def run():
            try:
                focus = None
                memory = None
                async with asyncio.timeout(45):
                    async with self._preparation_lock:
                        if "memory" in context.gaps:
                            memory = await self._semantic.remember(material, session)
                        if context.evidence and any(gap != "memory" for gap in context.gaps):
                            focus = await self._semantic.focus(material, session, context)
                if focus and focus.facts:
                    self._save_focus_facts(material.id, focus)
                if generation != self._generation or not self._session or self._session.id != session.id or self._session.status is not SessionStatus.ACTIVE:
                    return
                # Source artifacts were cached already. Conversation judgments may
                # only update the exact thread revision they actually considered.
                if len(self._session.messages) == revision:
                    changes = {}
                    if focus:
                        changes["focus_reference"] = focus
                    if memory:
                        changes["conversation_memory"] = memory
                    self._session = self._session.model_copy(update=changes)
                    self._save_session(self._session)
                    self._preparation_status = "ready"
                else:
                    self._preparation_status = "idle"
            except asyncio.CancelledError:
                pass
            except Exception:
                self._preparation_status = "unavailable"
        task = asyncio.create_task(run(), name=f"focus-{session.id}-{revision}")
        self._preparation_task = task
        self._preparation_tasks.add(task)
        task.add_done_callback(self._preparation_tasks.discard)
        def coalesce_latest(_task):
            if (not self._sending and generation == self._generation and self._session
                and self._session.id == session.id and len(self._session.messages) != revision):
                self._schedule_semantic_reference()
        task.add_done_callback(coalesce_latest)

    def _save_focus_facts(self, material_id, focus) -> None:
        current = next((item for item in self._materials if item.id == material_id), None)
        knowledge = current.analysis.knowledge if current and current.analysis else None
        if not knowledge or knowledge.source_hash != focus.source_hash or focus.knowledge_end > reading_end(current):
            return
        notes = {note.id: note for note in knowledge.notes}
        units = {unit.id for unit in knowledge.units}
        spans = {span.id for unit in knowledge.units for span in unit.paragraphs}
        notes.update({note.id: note for note in focus.facts if note.unit_id in units
            and note.knowledge_end <= knowledge.scope_end
            and set(note.dependency_ids) <= units and set(note.support_ids) <= spans})
        updated = current.model_copy(update={"analysis": current.analysis.model_copy(update={
            "knowledge": knowledge.model_copy(update={"notes": list(notes.values())})})})
        self._materials = [updated if item.id == material_id else item for item in self._materials]
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_material(updated)
        self._semantic.save_manifest(updated, updated.analysis.knowledge)
        if self._material and self._material.id == material_id:
            self._material = updated

    def _upsert_material(self, material: LearningMaterial) -> None:
        self._materials = [item for item in self._materials if item.id != material.id]
        self._materials.insert(0, material)
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_material(material)

    def _save_session(self, session: PracticeSession) -> None:
        if isinstance(self._event_store, SQLiteStore):
            self._event_store.save_session(session)

    def _stored_sessions_for(self, material_id: str) -> list[PracticeSession]:
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.list_sessions(material_id=material_id)
        return []

    @staticmethod
    def _review_event(outcome: ReviewOutcome, session_id: str):
        from lingualoop.core.domain import SessionEvent, SessionEventType
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
