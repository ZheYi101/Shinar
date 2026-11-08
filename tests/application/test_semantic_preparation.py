import asyncio
import json

import pytest

from shinar.application import LearningWorkbench
from shinar.application.semantic_preparation import SemanticPreparation, validate_unit_notes
from shinar.core.domain import LanguageEnum, LearningMaterial, ProficiencyLevel
from shinar.core.knowledge import ModelBudgetExceeded, ReasoningResponse
from shinar.core.knowledge_context import (
    assemble_turn_context,
    digest,
    safe_knowledge,
    source_units,
)
from shinar.infrastructure import SQLiteStore
from shinar.providers.mock import MockLearningLLMProvider


class SemanticMock(MockLearningLLMProvider):
    supports_free_chat = True

    def __init__(self):
        self.units = []
        self.briefs = 0
        self.focus_calls = 0
        self.fail_at = None

    async def prepare_source_unit(self, request):
        self.units.append(request)
        if self.fail_at == len(self.units):
            raise ConnectionError("offline")
        return await super().prepare_source_unit(request)

    async def summarize_reading(self, request):
        self.briefs += 1
        return await super().summarize_reading(request)

    async def prepare_focus(self, request):
        self.focus_calls += 1
        return await super().prepare_focus(request)


def text_material():
    return "\n\n".join(
        f"Mira and Ren discuss the river bridge in scene {index}. "
        + "Mira calls Ren a coward, although she also retreated from the bridge. " * 25
        for index in range(18)
    )


async def import_draft(work, text=None):
    return await work.load_material(
        title="River",
        content=text or text_material(),
        source_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.ENGLISH,
        native_language=LanguageEnum.CHINESE,
        learner_level=ProficiencyLevel.B2,
        auto_prepare=False,
    )


def test_source_units_cover_text_and_preserve_prefix_boundaries():
    text = text_material()
    whole = source_units(text, len(text))
    end = whole[0].end_char + 75
    partial = source_units(text, end)
    assert whole[0] == partial[0]
    assert partial[0].start_char == 0
    assert partial[-1].end_char == end
    assert all(left.end_char == right.start_char for left, right in zip(partial, partial[1:]))
    assert all(span.end_char <= unit.end_char for unit in partial for span in unit.paragraphs)


def test_notes_compute_provenance_and_reject_unknown_support():
    unit = source_units("Mira says Ren fled.\n", 20)[0]
    item = {
        "text": "Mira claims Ren fled.",
        "support_ids": [unit.paragraphs[0].id],
        "attribution": "Mira",
        "statement_kind": "claim",
    }
    note = validate_unit_notes({"notes": [item]}, unit)[0]
    assert note.knowledge_end == unit.end_char
    assert note.dependency_ids == [unit.id]
    with pytest.raises(ValueError):
        validate_unit_notes({"notes": [{**item, "support_ids": ["invented"]}]}, unit)
    forged = validate_unit_notes({"notes": [{**item, "knowledge_end": -1}]}, unit)[0]
    assert forged.knowledge_end == unit.end_char


def test_budget_reservations_survive_unknown_failure_and_restart(tmp_path):
    path = tmp_path / "budget.sqlite3"
    store = SQLiteStore(path)
    store.ensure_model_budget("owner", input_limit=1000, output_limit=500, request_limit=2)
    store.reserve_model_call("a", "owner", "unit", "x", 400, 300)
    store.settle_model_call("a", {}, "unknown")
    store.close()
    restored = SQLiteStore(path)
    with pytest.raises(ModelBudgetExceeded):
        restored.reserve_model_call("b", "owner", "unit", "y", 400, 300)
    restored.ensure_model_budget("owner", input_limit=1, output_limit=1, request_limit=1)
    assert restored.list_model_calls()[0]["actual_output"] is None
    # Reported usage settles the reservation instead of counting both.
    restored.settle_model_call("a", {"input_tokens": 100, "output_tokens": 50}, "completed")
    restored.reserve_model_call("b", "owner", "unit", "y", 400, 300)
    with pytest.raises(ModelBudgetExceeded):
        restored.reserve_model_call("c", "owner", "unit", "z", 1, 1)


def test_duplicate_active_call_is_not_sent_twice(tmp_path):
    store = SQLiteStore(tmp_path / "db")
    store.ensure_model_budget("owner", input_limit=5000, output_limit=5000, request_limit=10)
    store.reserve_model_call("a", "owner", "unit", "same", 10, 10)
    with pytest.raises(ModelBudgetExceeded):
        store.reserve_model_call("b", "owner", "unit", "same", 10, 10)


def test_automatic_preparation_is_ready_cached_and_profile_independent(tmp_path):
    async def run():
        provider = SemanticMock()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        draft = await import_draft(work)
        assert not provider.units and draft.read_through == 0
        work.set_reading_scope(len(draft.content))
        await work.prepare_current_material()
        knowledge = work.material.analysis.knowledge
        assert knowledge.status == "ready"
        assert len(knowledge.completed_unit_ids) == len(knowledge.units)
        assert knowledge.brief and not work.material.analysis.topics
        calls = len(provider.units), provider.briefs
        # Reconfirmation and explicit resume read validated artifacts, not the API.
        work.set_reading_scope(len(draft.content))
        await work.prepare_current_material()
        changed = work.profile.model_copy(
            update={"profile_level": ProficiencyLevel.A1, "target_language": LanguageEnum.JAPANESE}
        )
        await work.analyze_current_material(profile=changed)
        assert (len(provider.units), provider.briefs) == calls
        hits = work._event_store.list_knowledge_cache_hits()
        assert hits and all(row["hit_count"] >= 1 for row in hits)
        metadata = json.loads(work._event_store.list_model_calls()[0]["metadata"])
        assert metadata["source_hash"] == knowledge.source_hash
        assert metadata["source_ids"]
        await work.aclose()

    asyncio.run(run())


def test_failed_preparation_resumes_completed_units_after_restart(tmp_path):
    async def run():
        provider = SemanticMock()
        provider.fail_at = 2
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        assert work.material.analysis.knowledge.status == "partial"
        assert len(work.material.analysis.knowledge.completed_unit_ids) == 1
        await work.aclose()
        replacement = SemanticMock()
        restored = LearningWorkbench(replacement, event_store=SQLiteStore(tmp_path / "db"))
        await restored.prepare_current_material()
        assert restored.material.analysis.knowledge.status == "ready"
        assert len(replacement.units) == len(restored.material.analysis.knowledge.units) - 1
        records = restored._event_store.list_model_calls()
        assert any(record["status"] == "unknown" for record in records)
        await restored.aclose()

    asyncio.run(run())


def test_partial_scope_reuses_only_safe_units_and_no_full_brief(tmp_path):
    async def run():
        provider = SemanticMock()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        full = work.material.analysis.knowledge
        end = full.units[0].end_char + 70
        scoped = safe_knowledge(full, end)
        assert scoped.brief is None
        assert all(note.knowledge_end <= end for note in scoped.notes)
        count = len(provider.units)
        work.set_reading_scope(end)
        await work.prepare_current_material()
        assert len(provider.units) == count + 1  # only the cut-through unit
        assert work.material.analysis.knowledge.scope_end == end
        assert provider.units[-1].payload["paragraphs"][-1]["text"] in material.content[:end]
        await work.aclose()

    asyncio.run(run())


def test_auxiliary_sources_never_enter_body_brief_or_context(tmp_path):
    async def run():
        text = "FOREWORD\nThe hero dies at the end.\nPART ONE\nMira meets Ren at a bridge.\n1\nRen hesitates.\nAFTERWORD\nThe critic reveals a secret identity.\n"
        provider = SemanticMock()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, text)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        knowledge = work.material.analysis.knowledge
        assert {unit.source_kind for unit in knowledge.units} == {"foreword", "body", "author_note"}
        assert "dies" not in knowledge.brief.summary and "secret" not in knowledge.brief.summary
        await work.start_session()
        packet = assemble_turn_context(work.material, work.session, "What happened to Mira?")
        assert all(
            item.source_kind not in {"foreword", "author_note", "commentary"}
            for item in packet.evidence
        )
        serialized = packet.model_dump_json()
        assert "hero dies" not in serialized and "secret identity" not in serialized
        await work.aclose()

    asyncio.run(run())


def test_foreground_is_dialogue_only_and_custom_focus_never_builds_branches(tmp_path):
    async def run():
        provider = SemanticMock()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Mira calls Ren a coward. Ren disagrees.\n")
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        result = await work.start_session(custom_topic="Mira's unfair description")
        assert result.session.topic is None
        assert result.session.initial_focus == "Mira's unfair description"
        assert not work.material.analysis.topics
        count = len(provider.units)
        await work.send_message("Mira seems unfair to Ren.")
        assert len(provider.units) == count
        records = work._event_store.list_model_calls()
        assert len([record for record in records if record["workload"] == "dialogue"]) == 1
        assert work.session.messages[-1].metadata["timing"]["context_ms"] >= 0
        await work.aclose()

    asyncio.run(run())


def test_truncated_reasoning_never_becomes_a_cached_success(tmp_path):
    class Truncated(SemanticMock):
        async def prepare_source_unit(self, request):
            return ReasoningResponse(
                content='{"notes":[]}',
                usage={"input_tokens": 50, "output_tokens": 4096, "finish_reason": "length"},
            )

    async def run():
        work = LearningWorkbench(Truncated(), event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Mira hesitates at the bridge.")
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        assert work.material.analysis.knowledge.status == "failed"
        assert not work.material.analysis.knowledge.completed_unit_ids
        assert work._event_store.list_model_calls()[0]["status"] == "truncated"
        await work.aclose()

    asyncio.run(run())


def test_memory_rejects_speaker_inversion(tmp_path):
    from shinar.core.domain import Message, MessageRole, PracticeSession, SessionUserProfile

    class WrongMemory(SemanticMock):
        async def summarize_conversation(self, request):
            message = request.payload["messages"][0]
            return self._knowledge_response(
                {
                    "items": [
                        {
                            "text": "My belief",
                            "message_ids": [message["id"]],
                            "speaker": "assistant",
                            "kind": "stance",
                        }
                    ]
                }
            )

    async def run():
        store = SQLiteStore(tmp_path / "db")
        service = SemanticPreparation(WrongMemory(), store)
        material = LearningMaterial(
            title="river", source_language=LanguageEnum.ENGLISH, content="river"
        )
        session = PracticeSession(
            material_id=material.id,
            pattern_id="free-discussion",
            profile=SessionUserProfile(
                profile_level=ProficiencyLevel.B2,
                target_language=LanguageEnum.ENGLISH,
                native_language=LanguageEnum.CHINESE,
            ),
            messages=[
                Message(role=MessageRole.USER, content=f"stance {index}") for index in range(16)
            ],
        )
        with pytest.raises(ValueError):
            await service.remember(material, session)
        assert len(store.list_model_calls()) == 2

    asyncio.run(run())


def test_truncation_subdivides_input_and_reuses_success_without_larger_output_cap(tmp_path):
    class LengthOnLarge(SemanticMock):
        async def prepare_source_unit(self, request):
            size = sum(len(item["text"]) for item in request.payload["paragraphs"])
            self.units.append(request)
            if size > 7000:
                return ReasoningResponse(
                    content="",
                    usage={"input_tokens": 2000, "output_tokens": 4096, "finish_reason": "length"},
                )
            return await MockLearningLLMProvider.prepare_source_unit(self, request)

    async def run():
        provider = LengthOnLarge()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(
            work, "\n\n".join("Mira hesitates at the bridge. " * 32 for _ in range(12))
        )
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        assert work.material.analysis.knowledge.status == "ready"
        assert len(work.material.analysis.knowledge.units) > 1
        assert all(request.max_tokens == 4096 for request in provider.units)
        calls = len(provider.units)
        await work.prepare_current_material()
        assert len(provider.units) == calls
        assert any(call["status"] == "truncated" for call in work._event_store.list_model_calls())
        await work.aclose()

    asyncio.run(run())


def test_chat_can_finish_while_material_preparation_is_still_waiting(tmp_path):
    class Slow(SemanticMock):
        async def prepare_source_unit(self, request):
            self.started.set()
            await self.release.wait()
            return await super().prepare_source_unit(request)

    async def run():
        provider = Slow()
        provider.started, provider.release = asyncio.Event(), asyncio.Event()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Mira disagrees with Ren at the bridge.\n")
        work.set_reading_scope(len(material.content))
        await asyncio.wait_for(provider.started.wait(), 1)
        await work.start_session()
        result = await asyncio.wait_for(work.send_message("Mira seems angry at Ren."), 1)
        assert result.assistant_message and not work.material.analysis.preparation_complete
        provider.release.set()
        await work.prepare_current_material()
        assert work.material.analysis.knowledge.status == "ready"
        await work.aclose()

    asyncio.run(run())


def test_scope_manifests_restore_full_preparation_without_new_calls(tmp_path):
    async def run():
        provider = SemanticMock()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        summary = work.material.analysis.knowledge.brief.summary
        end = work.material.analysis.knowledge.units[0].end_char + 50
        work.set_reading_scope(end)
        await work.prepare_current_material()
        calls = len(provider.units), provider.briefs
        restored = work.set_reading_scope(len(material.content))
        assert restored.analysis.knowledge.status == "ready"
        assert restored.analysis.knowledge.brief.summary == summary
        assert (len(provider.units), provider.briefs) == calls
        await work.aclose()

    asyncio.run(run())


def test_local_term_warmup_populates_cache_without_reading_past_scope():
    from shinar.core.knowledge_context import cached_terms, prime_turn_index

    first, unread = "Mira waits at the bridge.\n", "Ren leaves after midnight.\n"
    material = LearningMaterial(
        title="river",
        content=first + unread,
        source_language=LanguageEnum.ENGLISH,
        read_through=len(first),
    )
    cached_terms.cache_clear()
    prime_turn_index(material)
    before = cached_terms.cache_info()
    cached_terms(first)
    assert cached_terms.cache_info().hits == before.hits + 1
    cached_terms(unread)
    assert cached_terms.cache_info().misses == before.misses + 1


def test_reusable_focus_facts_are_saved_in_scope_manifest(tmp_path):
    from shinar.core.knowledge import FocusReference, GroundedNote

    async def run():
        work = LearningWorkbench(SemanticMock(), event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Mira waits at the bridge.\n")
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        knowledge = work.material.analysis.knowledge
        unit = knowledge.units[0]
        fact = GroundedNote(
            id="new-source-fact",
            unit_id=unit.id,
            text="Mira waits.",
            support_ids=[unit.paragraphs[0].id],
            dependency_ids=[unit.id],
            knowledge_end=unit.end_char,
            attribution="narrator",
            statement_kind="narrated",
        )
        work._save_focus_facts(
            material.id,
            FocusReference(
                key="focus",
                source_hash=knowledge.source_hash,
                knowledge_end=unit.end_char,
                based_on_message_ids=[],
                facts=[fact],
            ),
        )
        restored = work._semantic.load_manifest(
            work.material, knowledge.scope_end, knowledge.generation_identity
        )
        assert any(note.id == fact.id for note in restored.notes)
        await work.aclose()

    asyncio.run(run())


def test_auxiliary_numbered_note_does_not_reenter_story():
    from shinar.core.knowledge_context import heading_kind

    assert heading_kind("12", "author_note") == "author_note"
    assert heading_kind("Part One", "foreword") == "body"


def test_cached_ready_manifest_rejects_missing_source_coverage(tmp_path):
    async def run():
        work = LearningWorkbench(SemanticMock(), event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        knowledge = work.material.analysis.knowledge
        broken = knowledge.model_copy(update={"units": knowledge.units[1:]})
        work._semantic.save_manifest(work.material, broken)
        assert work._semantic.load_manifest(work.material, knowledge.scope_end) is None
        assert safe_knowledge(broken, knowledge.scope_end).status != "ready"
        await work.aclose()

    asyncio.run(run())


def test_background_coalesces_latest_turn_without_accepting_stale_judgment(tmp_path):
    class SlowFocus(SemanticMock):
        async def prepare_focus(self, request):
            self.started.set()
            await self.release.wait()
            return await super().prepare_focus(request)

    async def run():
        provider = SlowFocus()
        provider.started, provider.release = asyncio.Event(), asyncio.Event()
        work = LearningWorkbench(provider, event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Mira waits at the bridge. Ren leaves.\n")
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        await work.start_session()
        await work.send_message("You said Mira left the bridge. Are you sure?")
        await asyncio.wait_for(provider.started.wait(), 1)
        old_task = work._preparation_task
        await work.send_message("You said Ren waited, but Mira waited at the bridge.")
        assert work._preparation_task is old_task
        assert work.session.focus_reference is None
        provider.release.set()
        await old_task
        for _ in range(50):
            await asyncio.sleep(0.01)
            if work.session.focus_reference:
                break
        assert provider.focus_calls == 2
        latest_user = next(m for m in reversed(work.session.messages) if m.role.value == "user")
        assert latest_user.id in work.session.focus_reference.based_on_message_ids
        await work.aclose()

    asyncio.run(run())


def test_context_preserves_paragraph_conclusion_and_short_adjacent_qualification():
    from shinar.core.domain import MaterialAnalysis, PracticeSession, SessionUserProfile
    from shinar.core.knowledge import GroundedNote, MaterialKnowledge

    paragraph = (
        "The children are playing. "
        + "The valley glows in the afternoon light. " * 65
        + "Her voice is absent from the chorus.\n"
    )
    neighbor = "He is describing a loss, rather than her presence.\n"
    material = LearningMaterial(
        title="valley", content=paragraph + neighbor, source_language=LanguageEnum.ENGLISH
    )
    unit = source_units(material.content, len(material.content))[0]
    note = GroundedNote(
        id="n1",
        unit_id=unit.id,
        text="A remembered chorus evokes absence.",
        attribution="narrator",
        statement_kind="interpretation",
        search_terms=["children", "chorus"],
        support_ids=[unit.paragraphs[0].id],
        dependency_ids=[unit.id],
        knowledge_end=unit.end_char,
    )
    material.analysis = MaterialAnalysis(
        summary="",
        knowledge=MaterialKnowledge(
            source_hash=digest(material.content),
            scope_end=len(material.content),
            units=[unit],
            notes=[note],
        ),
    )
    session = PracticeSession(
        material_id=material.id,
        pattern_id="free-discussion",
        profile=SessionUserProfile(
            profile_level=ProficiencyLevel.B2,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
        ),
    )
    context = assemble_turn_context(material, session, "The children’s chorus stayed with me.")
    assert any("Her voice is absent" in item.text for item in context.evidence)
    assert any(item.text == neighbor.rstrip() for item in context.evidence)
    assert all(
        item.text == material.content[item.start_char : item.end_char] for item in context.evidence
    )


def test_empty_unit_results_are_valid_but_not_a_completed_reading_brief(tmp_path):
    class EmptyNotes(SemanticMock):
        async def prepare_source_unit(self, request):
            return self._knowledge_response({"notes": []})

    async def run():
        work = LearningWorkbench(EmptyNotes(), event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work, "Contents\n")
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        knowledge = work.material.analysis.knowledge
        assert knowledge.completed_unit_ids and not knowledge.notes
        assert knowledge.status == "partial" and knowledge.brief is None
        assert not work.material.analysis.preparation_complete
        await work.aclose()

    asyncio.run(run())


def test_partial_semantic_scope_does_not_keep_unscoped_legacy_keywords_or_goals(tmp_path):
    from shinar.core.reading_scope import scope_material

    async def run():
        work = LearningWorkbench(SemanticMock(), event_store=SQLiteStore(tmp_path / "db"))
        material = await import_draft(work)
        work.set_reading_scope(len(material.content))
        await work.prepare_current_material()
        whole = work.material
        analysis = whole.analysis.model_copy(update={"keywords": ["unread identity"],
            "difficulties": ["later revelation"], "suggested_goals": ["explain the ending"]})
        scoped = scope_material(whole.model_copy(update={"analysis": analysis}),
            whole.analysis.knowledge.units[0].end_char)
        assert not scoped.analysis.keywords
        assert not scoped.analysis.difficulties
        assert not scoped.analysis.suggested_goals
        assert scoped.analysis.knowledge and not scoped.analysis.knowledge.brief
        await work.aclose()

    asyncio.run(run())
