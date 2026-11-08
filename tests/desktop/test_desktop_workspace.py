"""Real QML source and workspace interaction, with independent local stores."""

from PySide6.QtCore import QPointF, Qt, QMetaObject, Q_ARG, Q_RETURN_ARG, QRectF
from PySide6.QtTest import QTest

from tests.support.qt import until
from tests.support.scenarios import load_and_start, load_material, workspace_of
from shinar.application.source_document import python_to_utf16



def visible_item(window, name):
    pending = [window.contentItem()]
    while pending:
        obj = pending.pop()
        if obj.objectName() == name and obj.isVisible():
            return obj
        pending.extend(obj.childItems())
    raise AssertionError(name)


def source_ready(ws):
    until(lambda: ws._document_ready and bool(ws.sourceText))
    QTest.qWait(60)


def test_native_source_selection_copy_and_history_are_separate(desktop):
    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    window.setWidth(1440)
    ws.toggleSource()
    source_ready(ws)
    editor = visible_item(window, "sourceDocument")

    def position(offset):
        rect = QMetaObject.invokeMethod(
            editor, "positionToRectangle", Q_RETURN_ARG(QRectF), Q_ARG(int, offset)
        )
        return editor.mapToScene(QPointF(rect.x(), rect.y() + rect.height() / 2)).toPoint()

    for start, stop in ((1, 8), (8, 1)):
        QTest.mousePress(
            window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position(start)
        )
        QTest.mouseMove(window, position(stop), 80)
        QTest.mouseRelease(
            window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position(stop)
        )
        QTest.qWait(30)
        assert ws.snapshot().focus_kind == "text"
        assert ws.snapshot().quote == ws.sourceText[1:8]
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, position(12)
    )
    assert ws.snapshot().focus_kind == "paragraph"
    editor.forceActiveFocus()
    editor.setProperty("cursorPosition", 0)
    for _ in range(5):
        QTest.keyClick(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert ws.snapshot().quote == ws.sourceText[:5]
    QTest.keyClick(window, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    # Verify native clipboard through the existing QApplication instance.
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.clipboard().text() == ws.sourceText[:5]
    first = ws.snapshot()
    vm.draft = "I want to discuss this passage."
    vm.sendMessage(vm.draft)
    until(lambda: not vm.busy)
    assert vm.messages[1]["source"]["quote"] == first.quote
    ws.selectSource(5, 10)
    current = ws.snapshot()
    ws.previewMessage(vm.messages[1]["id"])
    source_ready(ws)
    assert ws.historicalSource and ws.snapshot() == current
    ws.closePreview()
    source_ready(ws)
    assert not ws.historicalSource and ws.snapshot() == current
    ws.previewMessage(vm.messages[1]["id"])
    source_ready(ws)
    ws.selectSource(0, 3)
    assert not ws.historicalSource and ws.snapshot().quote == ws.sourceText[:3]
    assert vm.messages[1]["source"]["quote"] == first.quote
    ws.toggleSource()
    assert vm.sessionActive and vm.draft == ""


def test_failed_turn_keeps_original_source_and_newer_draft(desktop):
    vm, window, scaffold, provider, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    ws.toggleSource()
    source_ready(ws)
    ws.selectSource(0, 8)
    original = ws.snapshot()
    provider.fail_reply = True
    vm.draft = "Please discuss the first passage."
    vm.sendMessage(vm.draft)
    ws.selectSource(8, 16)
    newer = ws.snapshot()
    vm.draft = "A second, unsent thought."
    until(lambda: not vm.busy)
    assert vm.messages[-1]["replyError"] and len(vm.messages) == 2
    vm.voice.retryReply(vm.messages[-1]["turnId"])
    until(lambda: not vm.busy)
    assert vm.draft == "A second, unsent thought."
    assert ws.snapshot() == newer
    assert vm.messages[1]["source"]["quote"] == original.quote
    assert len(vm.messages) == 3


def test_import_and_scope_do_not_replace_foreground_thread(desktop, tmp_path):
    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    thread_id = vm._workbench.session.id
    vm.draft = "An unfinished draft."
    ws.navigate("import")
    ws.setImportMode("paste")
    ws.importText = "Chapter One\n\n日本語😀と中文。\n\nRepeated.\n\nRepeated."
    ws.importTitle = "Another material"
    ws.navigate("library")
    ws.navigate("import")
    assert "Repeated." in ws.importText
    ws.commitImport()
    until(lambda: not vm.busy)
    source_ready(ws)
    imported_id = ws.browsingMaterialId
    assert ws.route == "scope" and imported_id != vm.selectedMaterialId
    assert vm._workbench.session.id == thread_id and vm.draft == "An unfinished draft."
    ws.locateSentence("Repeated.")
    assert ws.error and ws.pendingEnd == 0
    ws.selectSource(0, python_to_utf16(ws.sourceText, ws.sourceText.index("Repeated.")))
    assert ws.pendingEnd > 0
    assert not ws.material["confirmed"]
    ws.navigate("material")
    assert not ws.material["confirmed"]
    ws.openScope()
    ws.saveScope()
    until(lambda: not vm.busy)
    assert ws.material["confirmed"]
    assert vm._workbench.session.id == thread_id
    ws.newThreadPage()
    ws.startThread()
    until(lambda: not vm.busy)
    assert vm._workbench.session.material_id == imported_id
    ws.openThread(thread_id)
    assert vm.draft == "An unfinished draft."


def test_chapter_selection_search_clear_and_large_document(desktop):
    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    text = "Chapter One\n\n" + ("A readable sentence 😀.\n\n" * 3000) + "Chapter Two\n\n終わり。"
    load_material(vm, "Long", text, "english", "english", "chinese", "B1")
    until(lambda: not vm.busy, timeout=30000)
    ws = workspace_of(window)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.openScope()
    source_ready(ws)
    ws.markAllRead()
    ws.saveScope()
    until(lambda: not vm.busy, timeout=30000)
    ws.newThreadPage()
    ws.startThread()
    until(lambda: not vm.busy, timeout=30000)
    ws.toggleSource()
    source_ready(ws)
    assert len(ws.sourceText) == 40000 and ws.sourceHasMore
    original = ws.sourceText
    ws.loadMoreSource()
    assert ws.sourceText.startswith(original) and len(ws.sourceText) > 40000
    chapter = ws.sections[1]
    calls = vm._workbench._provider
    ws.selectSection(chapter["id"])
    source_ready(ws)
    assert ws.snapshot().base.start_char == chapter["start_char"]
    ws.selectSource(0, 0)
    assert ws.snapshot().focus is not None
    ws.clearSource()
    assert ws.snapshot().base is not None and ws.snapshot().focus is None
    ws.clearSource()
    assert ws.snapshot() is None
    ws.searchSource("終わり")
    until(lambda: len(ws.searchResults) == 1)
    assert ws.searchResults[0]["start"] == text.index("終わり")
    assert calls is vm._workbench._provider


def test_opening_remains_unsent_and_navigation_models_stay_stable(desktop, monkeypatch):
    vm, window, _, provider, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    original_id = vm._workbench.session.id
    vm.draft = "Old thread draft 😀."
    ws.saveEditor(python_to_utf16(vm.draft, len(vm.draft)), 0)
    ws.browseMaterial(vm.selectedMaterialId)
    ws.newThreadPage()
    opening = "My unsent opening. " * 40
    ws.openingDraft = opening

    async def forbidden_preparation(**kwargs):
        raise AssertionError("an unsent opening must not prepare a custom topic")

    monkeypatch.setattr(provider, "prepare_custom_topic", forbidden_preparation)
    ws.startThread()
    until(lambda: not vm.busy)
    assert vm.sessionActive and vm._workbench.session.id != original_id
    assert ws._source_section == "" and ws.sourceScroll == 0
    assert vm.draft == opening
    assert not any(message["role"] == "user" for message in vm.messages)
    changes = []
    ws.modelsChanged.connect(lambda: changes.append(True))
    ws.refresh()
    ws.refresh()
    assert changes == []
    ws.openThread(original_id)
    assert vm.draft == "Old thread draft 😀."
    QTest.qWait(30)
    assert ws.editorCursor == python_to_utf16(vm.draft, len(vm.draft))


def test_retyped_identical_draft_survives_reply_completion(desktop):
    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    text = "I would like to ask this again."
    vm.draft = text
    vm.sendMessage(text)
    vm.draft = "A different thought."
    vm.draft = text
    until(lambda: not vm.busy)
    assert vm.draft == text and len(vm.messages) == 3


def test_import_cancel_keeps_form_and_failed_replacement_cannot_import_old_file(desktop, tmp_path):
    vm, window, *_ = desktop
    ws = workspace_of(window)
    ws.navigate("import")
    ws.setImportMode("paste")
    ws.importText = "First paragraph.\n\n第二段😀。"
    ws.importTitle = "Kept title"
    ws.commitImport()
    until(lambda: not vm.busy)
    source_ready(ws)
    ws.markAllRead()
    pending = ws.pendingEnd
    assert ws.scopeEndPosition == python_to_utf16(ws.sourceText, len(ws.sourceText))
    ws.cancelScope()
    assert ws.route == "import" and not ws.material["confirmed"]
    assert ws.importText.endswith("第二段😀。") and ws.importTitle == "Kept title"
    ws.commitImport()
    until(lambda: not vm.busy)
    source_ready(ws)
    assert len(ws.materials) == 1 and ws.pendingEnd == pending
    ws.cancelScope()
    path = tmp_path / "valid.txt"
    path.write_text("A valid file.", encoding="utf-8")
    ws.setImportMode("file")
    ws.inspectFile(str(path))
    until(lambda: not ws.inspecting)
    assert ws.importTitle == "Kept title"
    ws.inspectFile(str(tmp_path / "missing.txt"))
    until(lambda: not ws.inspecting)
    assert ws.error and ws.importFile == ""
    ws.commitImport()
    assert ws.error == "请选择文件。" and len(ws.materials) == 1


def test_stale_history_preview_rejects_pending_document_result(desktop, monkeypatch):
    import asyncio

    vm, window, *_ = desktop
    vm._stt = vm._tts = None
    load_and_start(vm, window)
    ws = workspace_of(window)
    ws.toggleSource()
    source_ready(ws)
    ws.selectSource(0, 5)
    sent = ws.snapshot()
    vm.draft = "This passage matters."
    vm.sendMessage(vm.draft)
    until(lambda: not vm.busy)
    jobs = []
    monkeypatch.setattr(ws._worker, "submit", jobs.append)
    ws.loadSource("")
    material = vm._workbench.material
    vm._workbench._materials = [
        m.model_copy(update={"content": m.content + "Changed."}) if m.id == material.id else m
        for m in vm._workbench.materials
    ]
    ws.previewMessage(vm.messages[1]["id"])
    assert ws.historicalSource and ws.sourceStale and ws.sourceText == sent.quote
    result = asyncio.run(jobs.pop()())
    ws._completed(result, "")
    assert ws.sourceStale and ws.sourceText == sent.quote and not ws.documentReady


def test_source_resizing_and_recording_keep_business_thread(desktop):
    vm, window, _, _, _, audio, _ = desktop
    load_and_start(vm, window)
    vm.stopPlayback()
    ws = workspace_of(window)
    thread_id = vm._workbench.session.id
    audio.cleared = False
    vm.startRecording()
    assert ws.threadLocked
    ws.toggleSource()
    source_ready(ws)
    ws.startThread()
    ws.openThread("another-thread")
    for width in (1199, 1200, 360, 1440):
        window.setWidth(width)
        QTest.qWait(30)
        assert vm.voiceState == "recording" and not audio.cleared
        assert vm._workbench.session.id == thread_id
    ws.toggleSource()
    assert vm.voiceState == "recording" and not audio.cleared
    vm.cancelRecording()
