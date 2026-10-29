"""Desktop navigation and transient editing state; business state stays in Workbench."""
from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QObject, Property, QSettings, Qt, QUrl, Signal, Slot

from lingualoop.application.source_document import (
    document_paragraphs, document_sections, python_to_utf16, source_hash, utf16_to_python,
)
from lingualoop.core import (
    LanguageEnum, MaterialSourceType, PracticeOptions, PracticeMode,
    ProficiencyLevel, CorrectionIntensity, FeedbackTiming,
)
from lingualoop.core.knowledge import SourceSpan, TurnSourceSnapshot
from lingualoop.core.reading_scope import paragraph_boundary, reading_end
from lingualoop.desktop.worker import AsyncWorker
from lingualoop.infrastructure.material_import import ImportedMaterial, import_material_file, normalize_material


class DesktopWorkspaceController(QObject):
    changed = Signal()
    modelsChanged = Signal()
    documentChanged = Signal()
    sourceAppend = Signal(str)
    selectionRequested = Signal(int, int)
    editorRestoreRequested = Signal(int, float)
    focusComposerRequested = Signal()

    def __init__(self, viewmodel: Any, settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        self.vm = viewmodel
        self.workbench = viewmodel._workbench
        self.settings = settings if settings is not None else QSettings("LinguaLoop", "Workspace")
        self._route = "chat" if viewmodel.hasSession else "library"
        self._browsing = viewmodel.selectedMaterialId
        self._category = "appearance"
        self._collapsed = str(self.settings.value("sidebarCollapsed", "false")).lower() == "true"
        self._expanded: set[str] = {self._browsing} if self._browsing else set()
        self._materials: list[dict] = []
        self._threads: list[dict] = []
        self._states: dict[str, dict] = {}
        self._opening: dict[str, str] = {}
        self._cursor = 0
        self._scroll = 0.0
        self._source_scroll = 0.0
        self._source_stale = False
        self._document_ready = False
        self._pending_position = None
        self._source_open = False
        self._source_snapshot: TurnSourceSnapshot | None = None
        self._preview: TurnSourceSnapshot | None = None
        self._source_text = ""
        self._source_full = ""
        self._source_offset = 0
        self._source_limit = 0
        self._sections: list[dict] = []
        self._results: list[dict] = []
        self._source_material = ""
        self._source_end = 0
        self._source_section = ""
        self._error = ""
        self._import_mode = "file"
        self._import_title = ""
        self._import_text = ""
        self._import_language = viewmodel.preferences.targetLanguage
        self._imported: ImportedMaterial | None = None
        self._inspecting = False
        self._scope_pending: dict[str, int] = {}
        self._request = {"document": 0, "search": 0, "import": 0}
        self._worker = AsyncWorker(self)
        self._worker.completed.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        viewmodel.source_context_provider = self.snapshot
        for signal in (viewmodel.materialsChanged, viewmodel.historyChanged, viewmodel.sessionChanged):
            signal.connect(self.refresh)
        viewmodel.practiceStarted.connect(self._started)
        viewmodel.reviewReady.connect(lambda: self.navigate("review"))
        viewmodel.busyChanged.connect(self.changed)
        viewmodel.uiChanged.connect(self._voice_changed)
        self.refresh()

    def _voice_changed(self):
        # Notify navigation guards without rebuilding the material tree or source document.
        self.changed.emit()

    @Property(str, notify=changed)
    def route(self): return self._route

    @Property(str, notify=changed)
    def browsingMaterialId(self): return self._browsing

    @Property(str, notify=changed)
    def settingsCategory(self): return self._category

    @Slot(str)
    def setCategory(self, category: str):
        self._category = category
        self.changed.emit()

    @Property(bool, notify=changed)
    def collapsed(self): return self._collapsed

    @Slot()
    def toggleSidebar(self):
        self._collapsed = not self._collapsed
        self.settings.setValue("sidebarCollapsed", self._collapsed)
        self.changed.emit()

    @Property(bool, notify=changed)
    def threadLocked(self):
        return self.vm.busy or self.vm.voiceState in {"recording", "transcribing", "generating", "synthesizing", "playing"}

    @Property(list, notify=modelsChanged)
    def materials(self): return self._materials

    @Property(list, notify=modelsChanged)
    def threads(self):
        return [s for s in self._threads if s["materialId"] == self._browsing]

    @Property(dict, notify=modelsChanged)
    def material(self):
        return next((m for m in self._materials if m["id"] == self._browsing), {})

    @Slot()
    def refresh(self):
        sessions = self.workbench.list_sessions()
        active = self.workbench.session
        if active:
            sessions = [active, *(s for s in sessions if s.id != active.id)]
        self._threads = [{"id": s.id, "materialId": s.material_id,
            "title": s.topic.title if s.topic else next((m.content for m in s.messages if m.role.value == "user"), "新对话"),
            "preview": next((m.content for m in reversed(s.messages) if m.role.value == "assistant"), ""),
            "turns": sum(m.role.value == "user" for m in s.messages),
            "date": s.updated_at.astimezone().strftime("%m-%d %H:%M"),
            "active": s.status.value == "active", "selected": bool(active and s.id == active.id)} for s in sessions]
        self._materials = [{"id": m.id, "title": m.title,
            "language": {"japanese": "日语", "english": "英语", "chinese": "中文", "french": "法语", "germany": "德语", "spanish": "西班牙语"}.get(m.source_language.value, m.source_language.value),
            "type": Path(m.source_path).suffix[1:].upper() if m.source_path else m.source_type.value.upper(),
            "range": "范围未确认" if reading_end(m) == 0 else "已读完" if reading_end(m) == len(m.content) else f"{reading_end(m)/len(m.content):.0%}",
            "confirmed": reading_end(m) > 0, "expanded": m.id in self._expanded,
            "threads": [s for s in self._threads if s["materialId"] == m.id]} for m in self.workbench.materials]
        self.modelsChanged.emit()
        self.changed.emit()

    @Slot(str)
    def navigate(self, route: str):
        previous = self._route
        self._route = route
        self._error = ""
        if route == "chat" and previous != "chat" and self._source_open:
            self._preview = None
            self.loadSource(self._source_section)
        self.changed.emit()

    @Slot(str)
    def browseMaterial(self, material_id: str):
        if self.workbench.get_material(material_id):
            self._browsing = material_id
            self._expanded.add(material_id)
            self.navigate("material")
            self.refresh()

    @Slot(str)
    def toggleMaterial(self, material_id: str):
        if material_id in self._expanded:
            self._expanded.remove(material_id)
        else:
            self._expanded.add(material_id)
        self.refresh()

    def _key(self):
        return self.workbench.session.id if self.workbench.session else ""

    def _save_state(self):
        self._states[self._key()] = dict(cursor=self._cursor, scroll=self._scroll,
            source=self._source_snapshot, opened=self._source_open, section=self._source_section,
            source_scroll=self._source_scroll)

    @Slot(int, float)
    def saveEditor(self, cursor: int, scroll: float):
        self._cursor, self._scroll = cursor, scroll

    @Property(int, notify=changed)
    def editorCursor(self): return self._cursor

    @Property(float, notify=changed)
    def chatScroll(self): return self._scroll

    @Slot(str)
    def openThread(self, thread_id: str):
        if self.threadLocked:
            return
        self._save_state()
        self.vm.selectSession(thread_id)
        state = self._states.get(thread_id, {})
        self._cursor, self._scroll = state.get("cursor", len(self.vm.draft)), state.get("scroll", 0.0)
        self._source_scroll = state.get("source_scroll", 0.0)
        self._source_snapshot = state.get("source")
        self._preview = None
        self._source_open = state.get("opened", False)
        self._source_section = state.get("section", "")
        self._browsing = self.vm.selectedMaterialId
        self._expanded.add(self._browsing)
        self.settings.setValue("lastThreadId", thread_id)
        self.navigate("chat")
        if self._source_open:
            self.loadSource(self._source_section)
        self.refresh()
        self.editorRestoreRequested.emit(self._cursor, self._scroll)

    @Property(str, notify=changed)
    def openingDraft(self): return self._opening.get(self._browsing, "")

    @openingDraft.setter
    def openingDraft(self, value):
        self._opening[self._browsing] = value
        self.changed.emit()

    @Slot()
    def newThreadPage(self):
        if self.material.get("confirmed"):
            self.navigate("new")
        else:
            self.openScope()

    @Slot()
    def startThread(self):
        if self.threadLocked or not self._browsing:
            return
        self._save_state()
        if self.workbench.session:
            self.vm._session_drafts[self._key()] = self.vm.draft
        material_id, opening = self._browsing, self.openingDraft
        prefs = self.vm.preferences
        options = PracticeOptions(mode=PracticeMode(self.vm.practiceMode),
            role_description=self.vm.roleDescription, difficulty=ProficiencyLevel(prefs.difficulty),
            correction_intensity=CorrectionIntensity(prefs.correctionIntensity),
            feedback_timing=FeedbackTiming(prefs.feedbackTiming))
        self.vm._run_operation("正在开始对话…", lambda: self.workbench.start_session(
            material_id=material_id, new_thread=True, profile=self.vm._selected_profile(),
            custom_topic=opening or None, options=options), self.vm._after_started)

    def _started(self):
        self._source_snapshot, self._preview = None, None
        self._source_open = False
        self._cursor, self._scroll = 0, 0.0
        self._browsing = self.vm.selectedMaterialId
        self.vm.draft = self._opening.pop(self._browsing, "")
        self.navigate("chat")
        self.refresh()

    @Property(str, notify=changed)
    def error(self): return self._error

    def _fail(self, message):
        self._error = str(message)
        self.changed.emit()

    def _request_job(self, kind, function, callback):
        self._request[kind] += 1
        identity = self._request[kind]
        async def operation():
            try:
                value = await asyncio.to_thread(function)
                return kind, identity, callback, value, ""
            except Exception as exc:
                return kind, identity, callback, None, str(exc)
        self._worker.submit(operation)

    def _completed(self, result, error):
        if error:
            self._fail(error)
            return
        kind, identity, callback, value, error = result
        if self._request[kind] != identity:
            return
        if kind == "import":
            self._inspecting = False
        if error:
            self._fail(error)
        else:
            callback(value)
        self.changed.emit()

    @Property(str, notify=changed)
    def importMode(self): return self._import_mode

    @Slot(str)
    def setImportMode(self, mode: str):
        self._import_mode = mode
        self.changed.emit()

    @Property(str, notify=changed)
    def importTitle(self): return self._import_title

    @importTitle.setter
    def importTitle(self, value): self._import_title = value

    @Property(str, notify=changed)
    def importText(self): return self._import_text

    @importText.setter
    def importText(self, value): self._import_text = value

    @Property(str, notify=changed)
    def importLanguage(self): return self._import_language

    @importLanguage.setter
    def importLanguage(self, value): self._import_language = value

    @Property(str, notify=changed)
    def importFile(self): return Path(self._imported.source_path).name if self._imported else ""

    @Property(bool, notify=changed)
    def inspecting(self): return self._inspecting

    @Slot(str)
    def inspectFile(self, url: str):
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        self._inspecting = True
        self._error = ""
        self.changed.emit()
        def received(imported):
            self._imported = imported
            self._import_title = imported.title
        self._request_job("import", lambda: import_material_file(path), received)

    @Slot()
    def commitImport(self):
        if self.vm.busy or self._inspecting:
            return
        imported = self._imported
        if self._import_mode == "paste":
            normalized, diagnostics = normalize_material(self._import_text, ".txt")
            if not normalized:
                self._fail("请输入材料正文。")
                return
            imported = ImportedMaterial(self._import_title.strip() or normalized.splitlines()[0][:60],
                self._import_text, normalized, MaterialSourceType.TEXT, "", diagnostics)
        if not imported:
            self._fail("请选择文件。")
            return
        async def operation():
            return await self.workbench.store_imported_material(imported,
                title=self._import_title.strip() or None, source_language=LanguageEnum(self._import_language),
                target_language=LanguageEnum(self.vm.preferences.targetLanguage),
                native_language=LanguageEnum(self.vm.preferences.nativeLanguage),
                learner_level=self.vm._selected_profile().profile_level)
        def saved(material):
            self._browsing = material.id
            self._imported = None
            self._import_text = self._import_title = ""
            self.refresh()
            self.openScope()
        self.vm._run_operation("正在保存材料…", operation, saved)

    @Slot()
    def openScope(self):
        material = self.workbench.get_material(self._browsing)
        if material:
            self._scope_pending.setdefault(material.id, reading_end(material))
            self.navigate("scope")
            self.loadSource("")

    @Property(int, notify=changed)
    def pendingEnd(self): return self._scope_pending.get(self._browsing, 0)

    @Property(str, notify=changed)
    def scopeQuote(self):
        material = self.workbench.get_material(self._browsing)
        return material.content[max(0, self.pendingEnd-180):self.pendingEnd] if material else ""

    @Slot()
    def markAllRead(self):
        material = self.workbench.get_material(self._browsing)
        if material:
            self._scope_pending[material.id] = len(material.content)
            self.changed.emit()

    @Slot(str)
    def locateSentence(self, sentence: str):
        material = self.workbench.get_material(self._browsing)
        if not material or not sentence.strip():
            return
        matches = list(re.finditer(re.escape(sentence.strip()), material.content))
        if len(matches) != 1:
            self._fail("这段文字有多处匹配，请补充文字或直接点选末段。" if matches else "没有找到这段文字。")
            return
        self._scope_pending[material.id] = matches[0].end()
        self._show_position(matches[0].start(), matches[0].end())
        self._error = ""
        self.changed.emit()

    @Slot(float)
    def locatePercent(self, percent: float):
        material = self.workbench.get_material(self._browsing)
        if material:
            end = paragraph_boundary(material.content, max(1, min(100, percent)))
            self._scope_pending[material.id] = end
            self._show_position(max(0, end-100), end)
            self.changed.emit()

    @Slot()
    def saveScope(self):
        material_id, end = self._browsing, self.pendingEnd
        if self.vm.busy or not end:
            return
        async def operation():
            return self.workbench.set_reading_scope(end, material_id=material_id)
        def saved(_):
            self.vm.materialChanged.emit()
            self.vm.topicsChanged.emit()
            self.vm.materialsChanged.emit()
            self.refresh()
            self.navigate("material")
        self.vm._run_operation("正在保存已读范围…", operation, saved)

    @Property(bool, notify=changed)
    def sourceOpen(self): return self._source_open

    @Slot()
    def toggleSource(self):
        self._preview = None
        self._source_open = not self._source_open
        if self._source_open:
            self.loadSource(self._source_section)
        else:
            self.focusComposerRequested.emit()
        self.changed.emit()

    @Property(str, notify=documentChanged)
    def sourceText(self): return self._source_text

    @Property(list, notify=documentChanged)
    def sections(self): return self._sections

    @Property(list, notify=changed)
    def searchResults(self): return self._results

    @Property(bool, notify=changed)
    def historicalSource(self): return self._preview is not None

    @Property(bool, notify=changed)
    def sourceStale(self): return self._source_stale

    @Property(bool, notify=changed)
    def documentReady(self): return self._document_ready

    @Property(str, notify=documentChanged)
    def sourceLanguage(self):
        material = self.workbench.get_material(self._source_material)
        return material.source_language.value if material else ""

    @Property(float, notify=documentChanged)
    def sourceScroll(self): return self._source_scroll

    @Slot(float)
    def saveSourceScroll(self, value: float):
        if self._route == "chat" and not self._preview:
            self._source_scroll = value

    @Property(str, notify=changed)
    def sourceLabel(self):
        snapshot = self._preview or self._source_snapshot
        return snapshot.label if snapshot else ""

    @Property(bool, notify=changed)
    def hasSource(self): return self._source_snapshot is not None

    @Property(bool, notify=changed)
    def sourceHasMore(self): return self._source_offset + len(self._source_text) < self._source_limit

    @Slot(str)
    def loadSource(self, section_id: str):
        scope = self._route == "scope"
        session = self.workbench.session
        material_id = self._browsing if scope else session.material_id if session else self._browsing
        material = self.workbench.get_material(material_id)
        if not material:
            return
        end = len(material.content) if scope else session.options.read_through if session and session.options.read_through is not None else reading_end(material)
        self._source_material, self._source_end = material.id, end
        self._document_ready = False
        self._pending_position = None
        self._request["search"] += 1
        self._results = []
        def received(sections):
            self._source_stale = False
            self._document_ready = True
            self._sections = [s.model_dump() for s in sections]
            self._source_full = material.content
            section = next((s for s in sections if s.id == section_id), None)
            if not scope and not self._preview:
                self._source_section = section.id if section else ""
            self._source_offset = section.start_char if section else 0
            self._source_limit = section.end_char if section else end
            self._source_text = material.content[self._source_offset:min(self._source_limit, self._source_offset+40000)]
            self.documentChanged.emit()
            self.changed.emit()
            snapshot = self._preview or self._source_snapshot
            span = snapshot.focus if snapshot else None
            if self._pending_position:
                start, stop = self._pending_position
                self._pending_position = None
                self._show_position(start, stop)
            elif span:
                self._show_position(span.start_char, span.end_char)
        self._request_job("document", lambda: document_sections(material, end), received)
        self.changed.emit()

    @Slot()
    def loadMoreSource(self):
        start = self._source_offset + len(self._source_text)
        chunk = self._source_full[start:min(start+40000, self._source_limit)]
        if chunk:
            self._source_text += chunk
            self.sourceAppend.emit(chunk)
            self.changed.emit()

    def _snapshot(self, base=None, focus=None, kind=None, label=""):
        return TurnSourceSnapshot(material_id=self._source_material, source_hash=source_hash(self._source_full),
            read_through=self._source_end, base=base, focus=focus, focus_kind=kind,
            section_id=self._source_section or None, label=label,
            quote=self._source_full[(focus or base).start_char:(focus or base).end_char] if focus or base else "")

    @Slot(str)
    def selectSection(self, section_id: str):
        section = next((s for s in self._sections if s["id"] == section_id), None)
        if section and self._route != "scope" and not self._preview:
            self._source_snapshot = self._snapshot(base=SourceSpan(**{k: section[k] for k in ("id", "start_char", "end_char")}), label=section["label"])
        self._source_scroll = 0.0
        self.loadSource(section_id)
        self.changed.emit()

    @Slot(int, int)
    def selectSource(self, start: int, end: int):
        if self._preview or not self._document_ready:
            return
        try:
            a, b = sorted((utf16_to_python(self._source_text, start), utf16_to_python(self._source_text, end)))
            a, b = a+self._source_offset, b+self._source_offset
            if a == b:
                paragraphs = document_paragraphs(self._source_full, self._source_offset, self._source_limit)
                span = next((p for p in paragraphs if p.start_char <= a <= p.end_char), None)
                if not span:
                    return
                a, b = span.start_char, span.end_char
            if self._route == "scope":
                self._scope_pending[self._browsing] = b
            else:
                base = self._source_snapshot.base if self._source_snapshot else None
                span = SourceSpan(id=f"selection_{a}_{b}", start_char=a, end_char=b)
                self._source_snapshot = self._snapshot(base=base, focus=span,
                    kind="paragraph" if start == end else "text", label=self._source_full[a:b][:80])
            if start == end:
                self._show_position(a, b)
            self.changed.emit()
        except ValueError as exc:
            self._fail(exc)

    @Slot()
    def clearSource(self):
        if self._source_snapshot and self._source_snapshot.focus and self._source_snapshot.base:
            base = self._source_snapshot.base
            label = next((s["label"] for s in self._sections if s["id"] == base.id), "本章")
            self._source_snapshot = self._snapshot(base=base, label=label)
        else:
            self._source_snapshot = None
        self.changed.emit()

    def snapshot(self) -> TurnSourceSnapshot | None:
        return self._source_snapshot.model_copy(deep=True) if self._source_snapshot else None

    @Slot(str)
    def searchSource(self, query: str):
        text, end = self._source_full, self._source_end
        def search():
            return [{"start": m.start(), "end": m.end(), "text": text[max(0,m.start()-25):min(end,m.end()+70)]}
                for m in list(re.finditer(re.escape(query), text[:end], re.I))[:100]] if query.strip() else []
        self._request_job("search", search, self._set_results)

    def _set_results(self, results):
        self._results = results
        self.changed.emit()

    def _show_position(self, start, end):
        if not self._document_ready:
            self._pending_position = (start, end)
            return
        if not 0 <= start < end <= self._source_end:
            return
        if not self._source_offset <= start < end <= self._source_limit:
            self._source_offset = max(0, start-500)
            self._source_limit = self._source_end
            self._source_text = self._source_full[self._source_offset:min(self._source_limit, max(end, start+40000))]
            self.documentChanged.emit()
        while end > self._source_offset + len(self._source_text):
            previous_length = len(self._source_text)
            self.loadMoreSource()
            if len(self._source_text) == previous_length:
                return
        self.selectionRequested.emit(python_to_utf16(self._source_text, start-self._source_offset),
            python_to_utf16(self._source_text, end-self._source_offset))

    @Slot(int, int)
    def showSearchResult(self, start: int, end: int):
        self._show_position(start, end)

    @Slot(str)
    def previewMessage(self, message_id: str):
        session = self.workbench.session
        message = next((m for m in session.messages if m.id == message_id), None) if session else None
        if not message or not message.source_context:
            return
        self._preview = message.source_context.model_copy(deep=True)
        material = self.workbench.get_material(self._preview.material_id)
        self._source_open = True
        if not material or source_hash(material.content) != self._preview.source_hash or self._preview.index_version != "source-view-v1":
            self._source_stale = True
            self._source_text = self._preview.quote
            self._source_full = self._preview.quote
            self._source_offset = 0
            self._source_limit = self._source_end = len(self._source_text)
            self._sections = []
            self.documentChanged.emit()
            self._fail("原文版本已改变，显示发送时保存的引文。")
        else:
            self.loadSource(self._preview.section_id or "")
        self.changed.emit()

    @Slot()
    def closePreview(self):
        self._preview = None
        self.loadSource(self._source_section)
        self.changed.emit()

    def close(self):
        async def cleanup(): pass
        self._worker.close(cleanup)
