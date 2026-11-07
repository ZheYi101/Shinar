"""Material import, reading scope and reference preparation for the Workbench facade."""

from __future__ import annotations

import re
import asyncio
from pathlib import Path
from typing import Any

from lingualoop.core.domain import (
    LanguageEnum,
    LearningMaterial,
    MaterialTrack,
    MaterialSourceType,
    NormalizationStatus,
    ProficiencyLevel,
    SessionUserProfile,
    SessionStatus,
    SubtitleCue,
)
from lingualoop.infrastructure import SQLiteStore
from lingualoop.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from lingualoop.infrastructure.material_import import ImportedMaterial
from lingualoop.application.material_preparation import prepare_material, preparation_cache_key
from lingualoop.core.preparation_validation import validate_dialogue_preparation
from lingualoop.core.reading_scope import scope_material, reading_end
from lingualoop.core.material_context import dialogue_knowledge
from lingualoop.application.source_index import build_source_index
from lingualoop.application.semantic_preparation import analysis_with_knowledge
from lingualoop.core.knowledge_context import assemble_turn_context, digest
from lingualoop.core.knowledge import SourceSection


class MaterialWorkbench():
    def _uses_semantic(self) -> bool:
        return self._semantic.supported and bool(getattr(self._provider, "supports_free_chat", False)
            or (self._material and self._material.analysis and self._material.analysis.knowledge))

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
        source_sections: list[SourceSection] | None = None,
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
        if imported.epub_content is not None and self.source_asset_directory is not None:

            await run_blocking(BlockingRequest("save_source", (
                self.source_asset_directory, imported.epub_content, imported.normalized_content,
            )))
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

    @property
    def source_asset_directory(self) -> Path | None:
        """Local source files share the owning store's isolation and lifetime."""
        if isinstance(self._event_store, SQLiteStore):
            return self._event_store.path.with_suffix(".assets") / "sources"
        return None

    def get_material(self, material_id: str) -> LearningMaterial | None:
        return next((item for item in self._materials if item.id == material_id), None)

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

    async def prepare_material_reference(self, material_id: str, *, reanalyze: bool = False) -> LearningMaterial:
        """Explicit preparation for a browsed material, preserving the foreground thread."""
        self._require_idle_conversation()
        material = self.get_material(material_id)
        if material is None:
            raise ValueError("找不到材料。")
        previous = self._material, self._session, self._profile
        try:
            self._material, self._session, self._profile = material, None, material.profile
            if reanalyze:
                return await self.analyze_current_material(profile=material.profile)
            return await self.prepare_current_material()
        finally:
            prior, self._session, self._profile = previous
            self._material = self.get_material(prior.id) if prior else None

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



