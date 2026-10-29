from __future__ import annotations

import asyncio
import json

import pytest

from lingualoop.application import LearningWorkbench
from lingualoop.application.material_preparation import preparation_cache_key
from lingualoop.application.source_index import build_source_index
from lingualoop.core.domain import (
    DialoguePreparation, DiscussionTopic, LanguageEnum as L, LearningMaterial,
    MaterialAnalysis, MaterialCharacter, PreparedChunk, ProficiencyLevel, SessionUserProfile,
)
from lingualoop.core.material_context import dialogue_knowledge
from lingualoop.core.reading_scope import paragraph_boundary, scope_material
from lingualoop.infrastructure import SQLiteStore
from lingualoop.providers import MockLearningLLMProvider
from lingualoop.providers.openai_compatible import _compact_reply_packet, _dialogue_system_prompt


class FreeProvider(MockLearningLLMProvider):
    # Retain coverage of the shipped source-index-v1 compatibility path.
    supports_semantic_preparation = False
    supports_free_chat = True

    def __init__(self):
        self.analyzed = 0
        self.background = 0
        self.seen = []

    async def analyze_material(self, **kwargs):
        self.analyzed += 1
        raise AssertionError("Import must not generate a topic bank")

    async def stream_reply(self, **kwargs):
        self.seen.append(kwargs["material"])
        yield "The friend's return seems to matter to you."

    async def prepare_dialogue(self, *, material, session):
        self.background += 1
        self.seen.append(material)
        return DialoguePreparation(
            based_on_message_count=len(session.messages), predicted_intents=["friend's return"],
            response_points=["A friend returns to the station."],
            source_excerpts=["A friend returns to the station."],
            suggested_directions=["What changes when the friend returns?"],
        )


async def imported(work, text="A friend returns to the station.\nUNREAD_ENDING: the friend dies."):
    return await work.load_material(title="Book", content=text, source_language=L.ENGLISH,
        target_language=L.ENGLISH, native_language=L.CHINESE, learner_level=ProficiencyLevel.B1,
        auto_prepare=False)


def test_import_free_opening_partial_scope_and_restart(tmp_path):
    async def run():
        path = tmp_path / "free.sqlite3"
        provider = FreeProvider()
        work = LearningWorkbench(provider, event_store=SQLiteStore(path))
        original = await imported(work)
        assert provider.analyzed == 0 and original.analysis is None and original.read_through == 0
        with pytest.raises(ValueError, match="已读"):
            await work.start_session()
        end = original.content.index("UNREAD_ENDING")
        work.set_reading_scope(end)
        started = await work.start_session()
        assert started.session.topic is None and started.session.pattern_id == "free-discussion"
        assert started.session.options.read_through == end
        assert provider.background == 0
        await work.send_message("I liked the friend returning to the station.")
        await asyncio.sleep(0)
        assert provider.background == 0
        await work.send_message("That friend's return to the station feels hopeful.")
        await asyncio.sleep(0.03)
        assert provider.background == 1
        assert work.session.preparation.suggested_directions
        with pytest.raises(ValueError, match="结束"):
            work.set_reading_scope(len(original.content))
        assert all("UNREAD_ENDING" not in material.content for material in provider.seen)
        session_id = work.session.id
        await work.aclose()
        restored = LearningWorkbench(FreeProvider(), event_store=SQLiteStore(path))
        assert restored.session.id == session_id and len(restored.session.messages) == 5
        assert restored.session.reference_refresh_count == 1
        assert restored.material.read_through == end
        await restored.send_message("The friend returning to the station still feels hopeful.")
        await asyncio.sleep(0.03)
        assert restored._provider.background == 0  # Same source selection is already prepared.
        await restored.aclose()
    asyncio.run(run())


def test_legacy_global_overview_never_enters_partial_prompt():
    prefix = "A friend returns to the station.\n"
    suffix = "SECRET_ENDING: everybody dies."
    material = LearningMaterial(title="Book", source_language=L.ENGLISH, content=prefix + suffix,
        read_through=len(prefix), analysis=MaterialAnalysis(
            summary=suffix, outline=[suffix], characters=[MaterialCharacter(name="Friend", description=suffix)],
            topics=[DiscussionTopic(title=suffix, opening_question=suffix, source_excerpt=prefix.strip())],
            chunks=[PreparedChunk(start_char=0, end_char=len(prefix), summary="A reunion", source_excerpt=prefix.strip()),
                    PreparedChunk(start_char=len(prefix), end_char=len(prefix + suffix), summary=suffix, source_excerpt=suffix)]))
    scoped = scope_material(material)
    assert scoped.analysis.summary == "" and not scoped.analysis.topics and not scoped.analysis.characters
    packet = _compact_reply_packet(scoped, {}, None, "What about the friend?")
    assert "SECRET_ENDING" not in json.dumps(packet)
    assert "later events" in _dialogue_system_prompt(L.ENGLISH)


def test_progress_cache_separates_scope_and_preserves_paid_full_notes(tmp_path):
    async def run():
        work = LearningWorkbench(FreeProvider(), event_store=SQLiteStore(tmp_path / "scope.sqlite3"))
        original = await imported(work)
        profile = original.profile
        full = original.model_copy(update={"read_through": None,
            "analysis": MaterialAnalysis(summary="Paid whole-book notes", outline=["Full plot"])})
        _, key = preparation_cache_key(work._provider, full, profile)
        full = full.model_copy(update={"analysis_cache_key": key})
        work._material = full
        work._upsert_material(full)
        partial = work.set_reading_scope(original.content.index("UNREAD_ENDING"))
        assert partial.analysis.preparation_strategy == "source-index-v1"
        assert partial.analysis_cache_key != key
        restored = work.set_reading_scope(len(original.content))
        assert restored.analysis.summary == "Paid whole-book notes"
        await work.aclose()
    asyncio.run(run())


def test_index_is_grounded_and_foreground_packet_is_bounded():
    text = ("A friend returns to the station and brings a letter.\n" * 4000)
    material = LearningMaterial(title="Long book", source_language=L.ENGLISH, content=text)
    index = build_source_index(material)
    assert not index.topics and not index.characters and not index.overview_complete
    material = material.model_copy(update={"analysis": index})
    references = dialogue_knowledge(material, "Why did the friend bring a letter?")
    assert 1 <= len(references) <= 3
    assert all(quote in text for record in references for quote in record["quotes"])
    packet = _compact_reply_packet(material, {}, None, "Why did the friend bring a letter?")
    assert len(json.dumps(packet)) < 5000
    assert "branches" not in packet and "section_overview" not in packet


def test_percent_rounds_down_and_short_text_does_not_jump_ahead():
    text = "first paragraph\nsecond paragraph\nfinal secret"
    assert paragraph_boundary(text, 60) <= len(text) * 60 // 100
    assert paragraph_boundary(text, 100) == len(text)
    with pytest.raises(ValueError):
        paragraph_boundary(text, 0)


def test_failed_reference_attempts_are_capped_across_restart(tmp_path, monkeypatch):
    class Failing(FreeProvider):
        async def prepare_dialogue(self, **kwargs):
            self.background += 1
            raise RuntimeError("service unavailable")
    monkeypatch.setattr("lingualoop.application.learning_workbench.dialogue_knowledge",
                        lambda material, query: [{"section": query}])
    async def run():
        path = tmp_path / "budget.sqlite3"
        provider = Failing()
        work = LearningWorkbench(provider, event_store=SQLiteStore(path))
        original = await imported(work)
        work.set_reading_scope(original.content.index("UNREAD_ENDING"))
        await work.start_session()
        for turn in range(5):
            await work.send_message(f"The friend returns to the station {turn}.")
            await asyncio.sleep(0.01)
        assert provider.background == 3 and work.session.reference_refresh_count == 3
        assert len(work.session.messages) == 11
        await work.aclose()
        restored = LearningWorkbench(Failing(), event_store=SQLiteStore(path))
        await restored.send_message("Another view about the friend returning.")
        await asyncio.sleep(0.01)
        assert restored._provider.background == 0
        await restored.aclose()
    asyncio.run(run())
