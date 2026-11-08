"""Source contracts with real persistence and deterministic providers."""

import asyncio
from hashlib import sha256

import pytest

from shinar.application import LearningWorkbench
from shinar.application.source_document import (
    document_sections,
    python_to_utf16,
    utf16_to_python,
)
from shinar.core import LanguageEnum, ProficiencyLevel
from shinar.core.domain import Message, MessageRole
from shinar.core.knowledge import SourceSpan, TurnSourceSnapshot
from shinar.core.knowledge_context import assemble_turn_context
from shinar.core.source_reference import freeze_source_context
from shinar.infrastructure import SQLiteStore
from shinar.infrastructure.material_import import import_material_file
from shinar.providers import MockLearningLLMProvider


def snapshot(material, end, start=0, stop=None):
    stop = stop or end
    return TurnSourceSnapshot(
        material_id=material.id,
        source_hash=sha256(material.content.encode()).hexdigest(),
        read_through=end,
        focus=SourceSpan(id="selected", start_char=start, end_char=stop),
        focus_kind="text",
        label="选择",
        quote=material.content[start:stop],
    )


@pytest.mark.parametrize("text", ["中文😀段落", "日本語🧑‍💻とe\u0301", "abc"])
def test_qt_positions_round_trip_without_splitting_surrogates(text):
    for offset in range(len(text) + 1):
        assert utf16_to_python(text, python_to_utf16(text, offset)) == offset
    if "😀" in text:
        with pytest.raises(ValueError):
            utf16_to_python(text, python_to_utf16(text, text.index("😀")) + 1)


def test_structural_markdown_headings_and_old_json(tmp_path):
    path = tmp_path / "book.md"
    path.write_text(
        "# Beginning\n\nA 😀 sentence.\n\n## Inside\n\n日本語。\n\n# Ending\n\nBye.",
        encoding="utf-8",
    )
    imported = import_material_file(path)
    assert [s.label for s in imported.source_sections] == ["Beginning", "Inside", "Ending"]
    for s in imported.source_sections:
        assert imported.normalized_content[s.start_char : s.end_char].startswith(s.label)
    assert Message.model_validate({"role": "user", "content": "old"}).source_context is None


async def material_in(wb, text):
    return await wb.load_material(
        title="Book",
        content=text,
        source_language=LanguageEnum.ENGLISH,
        target_language=LanguageEnum.ENGLISH,
        native_language=LanguageEnum.CHINESE,
        learner_level=ProficiencyLevel.B1,
        auto_prepare=False,
    )


def test_multi_thread_progress_and_source_snapshot_are_frozen(tmp_path):
    async def scenario():
        store = SQLiteStore(tmp_path / "source.db")
        wb = LearningWorkbench(MockLearningLLMProvider(), event_store=store)
        material = await material_in(
            wb, "Chapter One\n\nA friend returned.\n\nChapter Two\n\nShe left."
        )
        first_end = material.content.index("Chapter Two")
        wb.set_reading_scope(first_end)
        first = (await wb.start_session()).session
        selected = snapshot(material, first_end, material.content.index("A friend"), first_end - 2)
        result = await wb.send_message("What do you think of this?", source_context=selected)
        user = next(m for m in result.session.messages if m.role is MessageRole.USER)
        assert user.source_context == selected
        assert len(result.session.messages) == 3
        wb.set_reading_scope(len(material.content), material_id=material.id)
        assert wb.session.options.read_through == first_end
        second = (await wb.start_session(material_id=material.id, new_thread=True)).session
        assert second.id != first.id
        assert store.get_session(first.id).status.value == "active"
        assert second.options.read_through == len(material.content)
        wb.select_session(first.id)
        assert wb.session.messages[1].source_context == selected
        assert len(wb.list_sessions(material.id)) == 2
        invalid = selected.model_copy(update={"read_through": len(material.content)})
        with pytest.raises(ValueError):
            await wb.send_message("invalid", source_context=invalid)
        assert len(wb.session.messages) == 3
        await wb.aclose()

    asyncio.run(scenario())


def test_scope_validation_and_context_contains_exact_selection(tmp_path):
    async def scenario():
        wb = LearningWorkbench(
            MockLearningLLMProvider(), event_store=SQLiteStore(tmp_path / "context.db")
        )
        material = await material_in(
            wb,
            "Chapter One\n\nAn irrelevant paragraph.\n\nThe exact selected sentence 😀.\n\nChapter Two\n\nUnread.",
        )
        end = material.content.index("Chapter Two")
        wb.set_reading_scope(end)
        await wb.start_session()
        a = material.content.index("exact")
        selected = snapshot(material, end, a, a + len("exact selected sentence 😀"))
        freeze_source_context(
            selected, material_id=material.id, text=material.content, read_through=end
        )
        context = assemble_turn_context(
            wb._session_material(), wb.session, "What about that?", source_context=selected
        )
        assert any(e.text == "exact selected sentence 😀" for e in context.evidence)
        assert all(e.end_char <= end for e in context.evidence)
        assert context.source_context.quote == ""
        for update in ({"quote": "wrong"}, {"source_hash": "changed"}, {"read_through": end + 1}):
            with pytest.raises(ValueError):
                freeze_source_context(
                    selected.model_copy(update=update),
                    material_id=material.id,
                    text=material.content,
                    read_through=end,
                )
        assert [s.label for s in document_sections(material, end)] == ["Chapter One"]
        await wb.aclose()

    asyncio.run(scenario())


def test_navigation_summaries_match_history_without_loading_full_sessions(tmp_path, monkeypatch):
    from shinar.core.domain import SessionSummary

    async def scenario():
        store = SQLiteStore(tmp_path / "summaries.db")
        wb = LearningWorkbench(MockLearningLLMProvider(), event_store=store)
        material = await material_in(wb, "A friend returned.\n\nShe had a different answer.")
        wb.set_reading_scope(len(material.content))
        first = (await wb.start_session()).session
        for number in range(6):
            await wb.send_message(f"What changed in their answer, turn {number}?")
        first = wb.session.model_copy(deep=True)
        second = (await wb.start_session(material_id=material.id, new_thread=True)).session
        other = await material_in(wb, "A different book.")
        wb.set_reading_scope(len(other.content))
        third = (await wb.start_session()).session
        expected = [SessionSummary.from_session(s) for s in (third, second, first)]

        def no_history(*args, **kwargs):
            raise AssertionError("navigation must not load full sessions")

        monkeypatch.setattr(store, "list_sessions", no_history)
        assert wb.list_session_summaries() == expected
        assert store.list_session_summaries(material.id) == expected[1:]
        assert store.list_session_summaries("missing") == []
        await wb.aclose()

    asyncio.run(scenario())
