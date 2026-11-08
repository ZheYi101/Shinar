"""Desktop navigation and transient editing state; business state stays in Workbench."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Property, QSettings, Qt, QTimer, QUrl, Slot

from shinar.application.source_document import (
    python_to_utf16,
)
from shinar.core import (
    LanguageEnum,
    MaterialSourceType,
    PracticeOptions,
    PracticeMode,
    ProficiencyLevel,
    CorrectionIntensity,
    FeedbackTiming,
)
from shinar.core.knowledge import TurnSourceSnapshot
from shinar.core.reading_scope import paragraph_boundary, reading_end
from shinar.desktop.presentation.operations import ProjectionChange
from shinar.desktop.tasks.worker import AsyncWorker
from shinar.desktop.shell.settings import ProductSettings
from shinar.infrastructure.blocking_jobs import BlockingRequest, run_blocking
from shinar.infrastructure.material_import import (
    ImportedMaterial,
    normalize_material,
)
from shinar.infrastructure.epub_reader import (
    ReaderBook,
)


from shinar.desktop.workspace.reading import ReaderWorkspaceMixin

class DesktopWorkspaceController(QObject, ReaderWorkspaceMixin):


    def __init__(self, viewmodel: Any, settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        self.vm = viewmodel
        self.workbench = viewmodel.workbench
        self.settings = settings if settings is not None else ProductSettings("Workspace")
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
        self._reader_book: ReaderBook | None = None
        self._reader_id = ""
        self._reader_error = ""
        self._reader_generation = -1
        self._reader_position = 0
        self._reader_target: tuple[int, int] | None = None
        self._error = ""
        self._closed = False
        self._import_mode = "file"
        self._import_title = ""
        self._import_text = ""
        self._import_language = viewmodel.preferences.targetLanguage
        self._imported: ImportedMaterial | None = None
        self._inspecting = False
        self._scope_pending: dict[str, int] = {}
        self._scope_return_route = "material"
        self._scope_import_material = ""
        self._request = {"document": 0, "search": 0, "import": 0}
        self._pending_search = None
        self._jobs = {}
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._search_after_pause)
        self._worker = AsyncWorker(self)
        self._worker.completed.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        viewmodel.source_context_provider = self.snapshot
        for signal in (
            viewmodel.materialsChanged,
            viewmodel.historyChanged,
            viewmodel.sessionChanged,
        ):
            signal.connect(self.refresh)
        viewmodel.practiceStarted.connect(self._started)
        viewmodel.reviewReady.connect(lambda: self.navigate("review"))
        viewmodel.busyChanged.connect(self.changed)
        viewmodel.uiChanged.connect(self._voice_changed)
        self.refresh()

    def _voice_changed(self):
        # Notify navigation guards without rebuilding the material tree or source document.
        self.changed.emit()

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def route(self):
        return self._route

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def browsingMaterialId(self):
        return self._browsing

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def settingsCategory(self):
        return self._category

    @Slot(str)
    def setCategory(self, category: str):
        self._category = category
        self.changed.emit()

    @Property(bool, notify=ReaderWorkspaceMixin.changed)
    def collapsed(self):
        return self._collapsed

    @Slot()
    def toggleSidebar(self):
        self._collapsed = not self._collapsed
        self.settings.setValue("sidebarCollapsed", self._collapsed)
        self.changed.emit()

    @Property(bool, notify=ReaderWorkspaceMixin.changed)
    def threadLocked(self):
        return self.vm.busy or self.vm.voiceState in {
            "recording",
            "transcribing",
            "generating",
            "synthesizing",
            "playing",
        }

    @Property(list, notify=ReaderWorkspaceMixin.modelsChanged)
    def materials(self):
        return self._materials

    @Property(list, notify=ReaderWorkspaceMixin.modelsChanged)
    def threads(self):
        return [s for s in self._threads if s["materialId"] == self._browsing]

    @Property(dict, notify=ReaderWorkspaceMixin.modelsChanged)
    def material(self):
        return next((m for m in self._materials if m["id"] == self._browsing), {})

    @Property(dict, notify=ReaderWorkspaceMixin.changed)
    def reference(self) -> dict[str, Any]:
        material = self.workbench.get_material(self._browsing)
        analysis = material.analysis if material else None
        knowledge = analysis.knowledge if analysis else None
        return {
            "summary": knowledge.brief.summary
            if knowledge and knowledge.brief
            else analysis.summary
            if analysis
            else "",
            "outline": [p.text for p in knowledge.brief.points]
            if knowledge and knowledge.brief
            else analysis.outline
            if analysis
            else [],
            "status": {
                "ready": QCoreApplication.translate("Desktop", "已整理"),
                "preparing": QCoreApplication.translate("Desktop", "正在整理"),
                "failed": QCoreApplication.translate("Desktop", "整理未完成"),
            }.get(knowledge.status, knowledge.status)
            if knowledge
            else QCoreApplication.translate("Desktop", "已有本地参考")
            if analysis
            else QCoreApplication.translate("Desktop", "尚未整理"),
        }

    @Slot(bool)
    def prepareBrowsing(self, reanalyze: bool) -> None:
        if self.threadLocked or not self.material.get("confirmed"):
            return
        material_id = self._browsing
        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在整理参考…"),
            lambda: self.workbench.prepare_material_reference(material_id, reanalyze=reanalyze),
            lambda _: self.refresh(),
        )

    @Slot()
    def refresh(self):
        sessions = self.workbench.list_session_summaries()
        active = self.workbench.session
        threads = [
            {
                "id": s.id,
                "materialId": s.material_id,
                "title": s.title or QCoreApplication.translate("Desktop", "新对话"),
                "preview": s.preview,
                "turns": s.turns,
                "date": s.updated_at.astimezone().strftime("%m-%d %H:%M"),
                "active": s.status.value == "active",
                "selected": bool(active and s.id == active.id),
            }
            for s in sessions
        ]
        materials = [
            {
                "id": m.id,
                "title": m.title,
                "language": {
                    "japanese": QCoreApplication.translate("Desktop", "日语"),
                    "english": QCoreApplication.translate("Desktop", "英语"),
                    "chinese": QCoreApplication.translate("Desktop", "中文"),
                    "french": QCoreApplication.translate("Desktop", "法语"),
                    "germany": QCoreApplication.translate("Desktop", "德语"),
                    "spanish": QCoreApplication.translate("Desktop", "西班牙语"),
                }.get(m.source_language.value, m.source_language.value),
                "type": Path(m.source_path).suffix[1:].upper()
                if m.source_path
                else m.source_type.value.upper(),
                "range": QCoreApplication.translate("Desktop", "范围未确认")
                if reading_end(m) == 0
                else QCoreApplication.translate("Desktop", "已读完")
                if reading_end(m) == len(m.content)
                else f"{reading_end(m) / len(m.content):.0%}",
                "confirmed": reading_end(m) > 0,
                "expanded": m.id in self._expanded,
                "threads": [s for s in threads if s["materialId"] == m.id],
            }
            for m in self.workbench.materials
        ]
        if threads != self._threads or materials != self._materials:
            self._threads, self._materials = threads, materials
            self.modelsChanged.emit()
        self.changed.emit()

    @Slot(str)
    def navigate(self, route: str):
        previous = self._route
        if route != previous and previous in {"scope", "chat"}:
            self._request["document"] += 1
            self._request["search"] += 1
            self._pending_position = None
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
        self._states[self._key()] = dict(
            cursor=self._cursor,
            scroll=self._scroll,
            source=self._source_snapshot,
            opened=self._source_open,
            section=self._source_section,
            source_scroll=self._source_scroll,
            reader_position=self._reader_position,
        )

    @Slot(int, float)
    def saveEditor(self, cursor: int, scroll: float):
        self._cursor, self._scroll = cursor, scroll

    @Property(int, notify=ReaderWorkspaceMixin.changed)
    def editorCursor(self):
        return self._cursor

    @Property(float, notify=ReaderWorkspaceMixin.changed)
    def chatScroll(self):
        return self._scroll

    @Slot(str)
    def openThread(self, thread_id: str):
        if self.threadLocked:
            return
        self._save_state()
        self.vm.selectSession(thread_id)
        if not self.workbench.session or self.workbench.session.id != thread_id:
            return
        self._request["document"] += 1
        self._request["search"] += 1
        state = self._states.get(thread_id, {})
        self._cursor, self._scroll = (
            state.get("cursor", python_to_utf16(self.vm.draft, len(self.vm.draft))),
            state.get("scroll", 0.0),
        )
        self._source_scroll = state.get("source_scroll", 0.0)
        self._reader_position = state.get("reader_position", 0)
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

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def openingDraft(self):
        return self._opening.get(self._browsing, "")

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
            self.vm.remember_draft()
        material_id = self._browsing
        prefs = self.vm.preferences
        profile = self.vm.selected_profile()
        options = PracticeOptions(
            mode=PracticeMode(self.vm.practiceMode),
            role_description=self.vm.roleDescription,
            difficulty=ProficiencyLevel(prefs.difficulty),
            correction_intensity=CorrectionIntensity(prefs.correctionIntensity),
            feedback_timing=FeedbackTiming(prefs.feedbackTiming),
        )
        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在开始对话…"),
            lambda: self.workbench.start_session(
                material_id=material_id,
                new_thread=True,
                profile=profile,
                custom_topic=None,
                options=options,
            ),
            self.vm.after_started,
        )

    def _started(self):
        self._source_snapshot, self._preview = None, None
        self._source_open = False
        self._source_section = ""
        self._source_scroll = 0.0
        self._reader_position = 0
        self._cursor, self._scroll = 0, 0.0
        self._browsing = self.vm.selectedMaterialId
        self.vm.draft = self._opening.pop(self._browsing, "")
        self.navigate("chat")
        self.refresh()

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def error(self):
        return self._error

    def _fail(self, message):
        self._error = str(message)
        self.changed.emit()

    def _request_job(self, kind, function, callback):
        if self._closed:
            return
        previous = self._jobs.pop(kind, None)
        if previous is not None:
            previous.cancel()
        self._request[kind] += 1
        identity = self._request[kind]

        async def operation():
            try:
                value = (await run_blocking(function) if isinstance(function, BlockingRequest)
                         else await asyncio.to_thread(function))
                return kind, identity, callback, value, ""
            except Exception as exc:
                return kind, identity, callback, None, str(exc)

        self._jobs[kind] = self._worker.submit(operation)

    def _completed(self, result, error):
        if self._closed:
            return
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

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def importMode(self):
        return self._import_mode

    @Slot(str)
    def setImportMode(self, mode: str):
        self._import_mode = mode
        self.changed.emit()

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def importTitle(self):
        return self._import_title

    @importTitle.setter
    def importTitle(self, value):
        self._import_title = value

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def importText(self):
        return self._import_text

    @importText.setter
    def importText(self, value):
        self._import_text = value

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def importLanguage(self):
        return self._import_language

    @importLanguage.setter
    def importLanguage(self, value):
        self._import_language = value

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def importFile(self):
        return Path(self._imported.source_path).name if self._imported else ""

    @Property(bool, notify=ReaderWorkspaceMixin.changed)
    def inspecting(self):
        return self._inspecting

    @Slot(str)
    def inspectFile(self, url: str):
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        previous_title, previous_file = self._import_title, self._imported
        self._imported = None
        self._inspecting = True
        self._error = ""
        self.changed.emit()

        def received(imported):
            self._imported = imported
            if self._import_title == previous_title and (
                not previous_title.strip()
                or previous_file
                and previous_title == previous_file.title
            ):
                self._import_title = imported.title

        self._request_job("import", BlockingRequest("import", (path,)), received)

    @Slot()
    def commitImport(self):
        if self.vm.busy or self._inspecting:
            return
        imported = self._imported
        if self._import_mode == "paste":
            normalized, diagnostics = normalize_material(self._import_text, ".txt")
            if not normalized:
                self._fail(QCoreApplication.translate("Desktop", "请输入材料正文。"))
                return
            imported = ImportedMaterial(
                self._import_title.strip() or normalized.splitlines()[0][:60],
                self._import_text,
                normalized,
                MaterialSourceType.TEXT,
                "",
                diagnostics,
            )
        if not imported:
            self._fail(QCoreApplication.translate("Desktop", "请选择文件。"))
            return

        title = self._import_title.strip() or None
        source_language = LanguageEnum(self._import_language)
        target_language = LanguageEnum(self.vm.preferences.targetLanguage)
        native_language = LanguageEnum(self.vm.preferences.nativeLanguage)
        level = self.vm.selected_profile().profile_level

        async def operation():
            return await self.workbench.store_imported_material(
                imported,
                title=title,
                source_language=source_language,
                target_language=target_language,
                native_language=native_language,
                learner_level=level,
            )

        def saved(material):
            self._browsing = material.id
            self._scope_import_material = material.id
            self.refresh()
            self.openScope("import")

        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在保存材料…"), operation, saved
        )

    @Slot()
    @Slot(str)
    def openScope(self, return_route: str = "material"):
        material = self.workbench.get_material(self._browsing)
        if material:
            self._scope_return_route = return_route
            self._scope_pending.setdefault(material.id, reading_end(material))
            self.navigate("scope")
            self.loadSource("")

    @Slot()
    def cancelScope(self):
        self.navigate(self._scope_return_route)

    @Property(int, notify=ReaderWorkspaceMixin.changed)
    def pendingEnd(self):
        return self._scope_pending.get(self._browsing, 0)

    @Property(int, notify=ReaderWorkspaceMixin.changed)
    def scopeEndPosition(self) -> int:
        if self._route != "scope" or self._source_material != self._browsing:
            return -1
        offset = self.pendingEnd - self._source_offset
        if not 0 < offset <= len(self._source_text):
            return -1
        return python_to_utf16(self._source_text, offset)

    @Property(str, notify=ReaderWorkspaceMixin.changed)
    def scopeQuote(self):
        material = self.workbench.get_material(self._browsing)
        return material.content[max(0, self.pendingEnd - 180) : self.pendingEnd] if material else ""

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
            self._fail(
                QCoreApplication.translate(
                    "Desktop", "这段文字有多处匹配，请补充文字或直接点选末段。"
                )
                if matches
                else QCoreApplication.translate("Desktop", "没有找到这段文字。")
            )
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
            self._show_position(max(0, end - 100), end)
            self.changed.emit()

    @Slot()
    def saveScope(self):
        material_id, end = self._browsing, self.pendingEnd
        if self.vm.busy or not end:
            return

        async def operation():
            return self.workbench.set_reading_scope(end, material_id=material_id)

        def saved(_):
            if material_id == self._scope_import_material:
                self._scope_import_material = ""
                self._imported = None
                self._import_text = self._import_title = ""
            self.vm.refresh_learning(ProjectionChange(scope=True))
            self.refresh()
            self.navigate("material")

        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在保存已读范围…"), operation, saved
        )


    def begin_shutdown(self):
        self._closed = True
        for kind in self._request:
            self._request[kind] += 1
        self._pending_search = None
        self._search_timer.stop()
        async def cleanup():
            pass

        self._worker.begin_shutdown(cleanup)

    def finish_shutdown(self) -> bool:
        return self._worker.finish_shutdown()

    def close(self):
        self.begin_shutdown()
        async def cleanup():
            pass
        self._worker.close(cleanup)
