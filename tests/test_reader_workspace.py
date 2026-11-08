"""The WebChannel uses the same source snapshots and rejects stale page identities."""

import asyncio

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings

from tests.test_desktop_workflow import qt_app, until  # noqa: F401
from tests.infrastructure.test_epub_reader import make_epub
from shinar.application import LearningWorkbench
from shinar.core import LanguageEnum, ProficiencyLevel
from shinar.desktop.preferences import DesktopPreferences
from shinar.desktop.viewmodel import LearningViewModel
from shinar.desktop.workspace import DesktopWorkspaceController
from shinar.infrastructure import SQLiteStore
from shinar.providers import MockLearningLLMProvider


@pytest.fixture
def reader_workspace(qt_app, tmp_path):
    imported = make_epub(
        tmp_path / "book.epub",
        ["<p>First 😀 sentence.</p><p>Repeated.</p>", "<p>Repeated.</p><p>Later secret.</p>"],
    )
    workbench = LearningWorkbench(
        MockLearningLLMProvider(), event_store=SQLiteStore(tmp_path / "test.sqlite3")
    )

    async def seed():
        material = await workbench.store_imported_material(
            imported,
            source_language=LanguageEnum.ENGLISH,
            target_language=LanguageEnum.ENGLISH,
            native_language=LanguageEnum.CHINESE,
            learner_level=ProficiencyLevel.B1,
        )
        workbench.select_material(material.id)
        workbench.set_reading_scope(material.content.index("Later secret."))
        await workbench.start_session()

    asyncio.run(seed())
    prefs = DesktopPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    vm = LearningViewModel(workbench, "Mock", preferences=prefs)
    ws = DesktopWorkspaceController(
        vm, QSettings(str(tmp_path / "workspace.ini"), QSettings.IniFormat)
    )
    ws.toggleSource()
    until(lambda: ws.documentReady)
    assert ws.readerAvailable
    yield ws, vm, workbench
    ws.close()
    vm.close()


def test_reader_selection_is_exact_and_repeated_passages_are_not_first_matches(reader_workspace):
    ws, vm, wb = reader_workspace
    a = wb.material.content.rindex("Repeated.")
    ws.selectReaderRange(ws.readerId, a, a + 9, "text")
    selected = ws.snapshot()
    assert selected.focus.start_char == a and selected.quote == "Repeated."
    vm.draft = "I mean the second occurrence."
    vm.sendMessage(vm.draft)
    until(lambda: not vm.busy)
    assert vm.messages[1]["source"]["focus"]["start_char"] == a
    ws.selectReaderRange(ws.readerId, 0, ws._source_end + 1, "text")
    assert ws.snapshot() == selected
    ws.selectReaderRange(ws.readerId, a, a + 9, "invented")
    assert ws.snapshot() == selected


def test_old_page_events_are_ignored_after_new_load_and_navigation(reader_workspace):
    ws, _, wb = reader_workspace
    identity = ws.readerId
    a = wb.material.content.index("First")
    ws.selectReaderRange(identity, a, a + 5, "paragraph")
    selected = ws.snapshot()
    ws.loadSource("")
    ws.selectReaderRange(identity, a + 1, a + 4, "text")
    assert ws.snapshot() == selected
    until(lambda: ws.documentReady and ws.readerId != identity)
    assert ws.reader_document(identity) == {}
    identity = ws.readerId
    ws.navigate("settings")
    ws.selectReaderRange(identity, a + 1, a + 4, "text")
    assert ws.snapshot() == selected
    assert ws.reader_document(identity) == {}


def test_search_outside_selected_chapter_reopens_authorized_source(reader_workspace):
    ws, _, wb = reader_workspace
    ws.selectSection(ws.sections[0]["id"])
    until(lambda: ws.documentReady)
    assert ws.snapshot().base is not None
    start = wb.material.content.rindex("Repeated.")
    ws.showSearchResult(start, start + 9)
    until(lambda: ws.documentReady and ws._reader_target == (start, start + 9))
    assert ws.reader_document(ws.readerId)["target"] == (start, start + 9)
    ws.selectReaderRange(ws.readerId, start, start + 9, "text")
    assert ws.snapshot().quote == "Repeated."
    assert ws.snapshot().focus.start_char == start
    assert ws.snapshot().base is None and ws.snapshot().section_id is None


def test_debounced_search_uses_latest_query_and_rejects_departed_page(reader_workspace):
    from PySide6.QtTest import QTest

    ws, _, _ = reader_workspace
    ws.scheduleSourceSearch("Repeated")
    ws.scheduleSourceSearch("First")
    until(lambda: len(ws.searchResults) == 1)
    assert "First" in ws.searchResults[0]["text"]
    previous = ws.searchResults
    ws.scheduleSourceSearch("Repeated")
    ws.navigate("settings")
    QTest.qWait(250)
    assert ws.searchResults == previous


def test_reader_pending_boundary_does_not_commit_and_preview_keeps_current_focus(reader_workspace):
    ws, vm, wb = reader_workspace
    a = wb.material.content.index("First")
    ws.selectReaderRange(ws.readerId, a, a + len("First 😀"), "text")
    first = ws.snapshot()
    vm.sendMessage("Please discuss this detail.")
    until(lambda: not vm.busy)
    a = wb.material.content.rindex("Repeated.")
    ws.selectReaderRange(ws.readerId, a, a + 9, "paragraph")
    current = ws.snapshot()
    ws.previewMessage(vm.messages[1]["id"])
    until(lambda: ws.documentReady)
    assert ws.historicalSource and ws.snapshot() == current
    assert ws.reader_document(ws.readerId)["target"] == (
        first.focus.start_char,
        first.focus.end_char,
    )
    ws.closePreview()
    until(lambda: ws.documentReady)
    assert ws.snapshot() == current
    ws.browseMaterial(wb.material.id)
    ws.openScope()
    until(lambda: ws.documentReady)
    before = wb.material.read_through
    ws.selectReaderRange(ws.readerId, first.focus.start_char, first.focus.end_char, "text")
    assert ws.pendingEnd == first.focus.end_char and wb.material.read_through == before
    ws.cancelScope()
    assert wb.material.read_through == before
