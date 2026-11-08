"""Desktop navigation and transient editing state; business state stays in Workbench."""

from __future__ import annotations

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
from shinar.core.reading_scope import paragraph_boundary, reading_end
from shinar.desktop.presentation.operations import ProjectionChange
from shinar.desktop.tasks.worker import AsyncWorker
from shinar.desktop.shell.settings import ProductSettings
from shinar.infrastructure.blocking_jobs import BlockingRequest
from shinar.infrastructure.material_import import (
    ImportedMaterial,
    normalize_material,
)


from shinar.desktop.workspace.reading import ReaderPropertiesMixin
from shinar.desktop.workspace.reading_state import (
    ReadingCoordinator,
    ReadingRuntime,
    ReadingContext,
)
from shinar.desktop.workspace.import_editor import ImportEditor
from shinar.desktop.workspace.navigation import WorkspaceNavigation
from shinar.desktop.workspace.jobs import WorkspaceJobs
from shinar.desktop.presentation.conversation_presentation import display_value, freeze


class DesktopWorkspaceController(QObject, ReaderPropertiesMixin):
    def __init__(
        self,
        viewmodel: Any,
        settings: QSettings | None = None,
        parent=None,
        *,
        worker_factory=AsyncWorker,
    ):
        super().__init__(parent)
        self.vm = viewmodel
        self.workbench = viewmodel.workbench
        self.settings = settings if settings is not None else ProductSettings("Workspace")
        self._navigation = WorkspaceNavigation(
            "chat" if viewmodel.hasSession else "library",
            viewmodel.selectedMaterialId,
            str(self.settings.value("sidebarCollapsed", "false")).lower() == "true",
        )
        self._imports = ImportEditor(viewmodel.preferences.targetLanguage)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._search_after_pause)
        self._worker = worker_factory(self)
        self._worker.jobCompleted.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self._jobs = WorkspaceJobs(
            self._worker.submit_job, self._worker.cancel_job, self._worker.forget_job
        )
        self._reading = ReadingCoordinator(
            ReadingRuntime(
                self._reading_context,
                self.workbench.get_material,
                self._reading_session,
                self._request_job,
                self.changed.emit,
                self.documentChanged.emit,
                self.sourceAppend.emit,
                self.selectionRequested.emit,
                self.readerSelectionRequested.emit,
                self.focusComposerRequested.emit,
                self._fail,
                self._search_timer.start,
                self.workbench.source_asset_directory,
                freeze(
                    {
                        "reader_failed": QCoreApplication.translate(
                            "Desktop", "书籍排版暂不可用，已显示文本。"
                        ),
                        "chapter": QCoreApplication.translate("Desktop", "本章"),
                        "stale": QCoreApplication.translate(
                            "Desktop", "原文版本已改变，显示发送时保存的引文。"
                        ),
                    }
                ),
            )
        )
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

    @property
    def navigation_snapshot(self):
        return self._navigation.snapshot

    @property
    def import_snapshot(self):
        return self._imports.snapshot

    @property
    def reading_snapshot(self):
        return self._reading.state_snapshot

    def _reading_context(self):
        return ReadingContext(self.route, self.browsingMaterialId)

    def _reading_session(self):
        session = self.workbench.session
        return session.model_copy(deep=True) if session else None

    def _task_failed(self, kind, message):
        if kind == "import":
            self._imports.failed()
        self._fail(message)

    def _voice_changed(self):
        # Notify navigation guards without rebuilding the material tree or source document.
        self.changed.emit()

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def route(self):
        return self._navigation.snapshot.route

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def browsingMaterialId(self):
        return self._navigation.snapshot.browsing

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def settingsCategory(self):
        return self._navigation.snapshot.category

    @Slot(str)
    def setCategory(self, category: str):
        self._navigation.category(category)
        self.changed.emit()

    @Property(bool, notify=ReaderPropertiesMixin.changed)
    def collapsed(self):
        return self._navigation.snapshot.collapsed

    @Slot()
    def toggleSidebar(self):
        self._navigation.collapse()
        self.settings.setValue("sidebarCollapsed", self._navigation.snapshot.collapsed)
        self.changed.emit()

    @Property(bool, notify=ReaderPropertiesMixin.changed)
    def threadLocked(self):
        return self.vm.busy or self.vm.voiceState in {
            "recording",
            "transcribing",
            "generating",
            "synthesizing",
            "playing",
        }

    @Property(list, notify=ReaderPropertiesMixin.modelsChanged)
    def materials(self):
        return display_value(self._navigation.snapshot.materials)

    @Property(list, notify=ReaderPropertiesMixin.modelsChanged)
    def threads(self):
        return [
            display_value(s)
            for s in self._navigation.snapshot.threads
            if s["materialId"] == self._navigation.snapshot.browsing
        ]

    @Property(dict, notify=ReaderPropertiesMixin.modelsChanged)
    def material(self):
        return display_value(
            next(
                (
                    m
                    for m in self._navigation.snapshot.materials
                    if m["id"] == self._navigation.snapshot.browsing
                ),
                {},
            )
        )

    @Property(dict, notify=ReaderPropertiesMixin.changed)
    def reference(self) -> dict[str, Any]:
        material = self.workbench.get_material(self._navigation.snapshot.browsing)
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
            else list(analysis.outline)
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
        material_id = self._navigation.snapshot.browsing
        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在整理参考…"),
            lambda workbench=self.workbench: workbench.prepare_material_reference(
                material_id, reanalyze=reanalyze
            ),
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
                "expanded": m.id in self._navigation.snapshot.expanded,
                "threads": [s for s in threads if s["materialId"] == m.id],
            }
            for m in self.workbench.materials
        ]
        if self._navigation.models(threads, materials):
            self.modelsChanged.emit()
        self.changed.emit()

    @Slot(str)
    def navigate(self, route: str):
        previous = self.route
        if route != previous and previous in {"scope", "chat"}:
            self._reading.invalidate()
        self._navigation.route(route)
        if previous == "scope" and route != "scope":
            self._reading.restore_current()
        if route == "chat" and previous != "chat" and self.sourceOpen:
            self._reading.closePreview()
        self.changed.emit()

    @Slot(str)
    def browseMaterial(self, material_id: str):
        if self.workbench.get_material(material_id):
            self._navigation.browse(material_id)
            self._navigation.expand(material_id)
            self.navigate("material")
            self.refresh()

    @Slot(str)
    def toggleMaterial(self, material_id: str):
        self._navigation.toggle(material_id)
        self.refresh()

    def _key(self):
        return self.workbench.session.id if self.workbench.session else ""

    def _save_state(self):
        self._navigation.remember(self._key())
        self._reading.remember(self._key())

    @Slot(int, float)
    def saveEditor(self, cursor: int, scroll: float):
        self._navigation.editor(cursor, scroll)

    @Property(int, notify=ReaderPropertiesMixin.changed)
    def editorCursor(self):
        return self._navigation.snapshot.cursor

    @Property(float, notify=ReaderPropertiesMixin.changed)
    def chatScroll(self):
        return self._navigation.snapshot.scroll

    @Slot(str)
    def openThread(self, thread_id: str):
        if self.threadLocked:
            return
        self._save_state()
        self.vm.selectSession(thread_id)
        if not self.workbench.session or self.workbench.session.id != thread_id:
            return
        self._navigation.restore(thread_id, python_to_utf16(self.vm.draft, len(self.vm.draft)))
        self._reading.restore(thread_id)
        self._navigation.browse(self.vm.selectedMaterialId)
        self._navigation.expand(self.browsingMaterialId)
        self.settings.setValue("lastThreadId", thread_id)
        self.navigate("chat")
        if self.sourceOpen:
            self.loadSource(self.reading_snapshot["section"])
        self.refresh()
        self.editorRestoreRequested.emit(self.editorCursor, self.chatScroll)

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def openingDraft(self):
        return self._navigation.snapshot.opening.get(self._navigation.snapshot.browsing, "")

    @openingDraft.setter
    def openingDraft(self, value):
        self._navigation.opening(value)
        self.changed.emit()

    @Slot()
    def newThreadPage(self):
        if self.material.get("confirmed"):
            self.navigate("new")
        else:
            self.openScope()

    @Slot()
    def startThread(self):
        if self.threadLocked or not self._navigation.snapshot.browsing:
            return
        self._save_state()
        if self.workbench.session:
            self.vm.remember_draft()
        material_id = self._navigation.snapshot.browsing
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
            lambda workbench=self.workbench: workbench.start_session(
                material_id=material_id,
                new_thread=True,
                profile=profile,
                custom_topic=None,
                options=options,
            ),
            self.vm.after_started,
        )

    def _started(self):
        self._reading.reset_thread()
        self._navigation.editor(0, 0.0)
        self._navigation.browse(self.vm.selectedMaterialId)
        self.vm.draft = self._navigation.take_opening()
        self.navigate("chat")
        self.refresh()

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def error(self):
        return self._navigation.snapshot.error

    def _fail(self, message):
        self._navigation.error(str(message))
        self.changed.emit()

    def _request_job(self, kind, function, callback):
        if self._navigation.snapshot.closed:
            return
        lane = (
            self._imports.tasks
            if kind == "import"
            else self._reading.document_tasks
            if kind == "document"
            else self._reading.search_tasks
        )
        session = self.workbench.session
        self._jobs.start(
            lane,
            function,
            callback,
            lambda message: self._task_failed(kind, message),
            self.browsingMaterialId,
            session.id if session else "",
        )

    def _completed(self, task, result, error):
        if self._jobs.deliver(task, result, error):
            self.changed.emit()

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def importMode(self):
        return self._imports.snapshot.mode

    @Slot(str)
    def setImportMode(self, mode: str):
        self._imports.mode(mode)
        self.changed.emit()

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def importTitle(self):
        return self._imports.snapshot.title

    @importTitle.setter
    def importTitle(self, value):
        self._imports.title(value)

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def importText(self):
        return self._imports.snapshot.text

    @importText.setter
    def importText(self, value):
        self._imports.text(value)

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def importLanguage(self):
        return self._imports.snapshot.language

    @importLanguage.setter
    def importLanguage(self, value):
        self._imports.language(value)

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def importFile(self):
        return self._imports.filename

    @Property(bool, notify=ReaderPropertiesMixin.changed)
    def inspecting(self):
        return self._imports.snapshot.inspecting

    @Slot(str)
    def inspectFile(self, url: str):
        if self._navigation.snapshot.closed:
            return
        path = QUrl(url).toLocalFile() if url.startswith("file:") else url
        previous = self._imports.inspect()
        self._navigation.error("")
        self.changed.emit()
        self._request_job(
            "import",
            BlockingRequest("import", (path,)),
            lambda imported: self._imports.receive(imported, previous),
        )

    @Slot()
    def commitImport(self):
        if self.vm.busy or self._imports.snapshot.inspecting:
            return
        imported = self._imports.snapshot.file.material() if self._imports.snapshot.file else None
        if self._imports.snapshot.mode == "paste":
            normalized, diagnostics = normalize_material(self._imports.snapshot.text, ".txt")
            if not normalized:
                self._fail(QCoreApplication.translate("Desktop", "请输入材料正文。"))
                return
            imported = ImportedMaterial(
                self._imports.snapshot.title.strip() or normalized.splitlines()[0][:60],
                self._imports.snapshot.text,
                normalized,
                MaterialSourceType.TEXT,
                "",
                diagnostics,
            )
        if not imported:
            self._fail(QCoreApplication.translate("Desktop", "请选择文件。"))
            return

        title = self._imports.snapshot.title.strip() or None
        source_language = LanguageEnum(self._imports.snapshot.language)
        target_language = LanguageEnum(self.vm.preferences.targetLanguage)
        native_language = LanguageEnum(self.vm.preferences.nativeLanguage)
        level = self.vm.selected_profile().profile_level

        async def operation(workbench=self.workbench):
            return await workbench.store_imported_material(
                imported,
                title=title,
                source_language=source_language,
                target_language=target_language,
                native_language=native_language,
                learner_level=level,
            )

        def saved(material):
            self._navigation.browse(material.id)
            self._reading.imported(material.id)
            self.refresh()
            self.openScope("import")

        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在保存材料…"), operation, saved
        )

    @Slot()
    @Slot(str)
    def openScope(self, return_route: str = "material"):
        material = self.workbench.get_material(self.browsingMaterialId)
        if material:
            self._reading.scope_begin(material, return_route)
            self.navigate("scope")
            self.loadSource("")

    @Slot()
    def cancelScope(self):
        self.navigate(self._reading.scope_return_route)

    @Property(int, notify=ReaderPropertiesMixin.changed)
    def pendingEnd(self):
        return self._reading.pendingEnd

    @Property(int, notify=ReaderPropertiesMixin.changed)
    def scopeEndPosition(self) -> int:
        if (
            self._navigation.snapshot.route != "scope"
            or self._reading.source_material != self._navigation.snapshot.browsing
        ):
            return -1
        offset = self.pendingEnd - self._reading.source_offset
        if not 0 < offset <= len(self._reading.sourceText):
            return -1
        return python_to_utf16(self._reading.sourceText, offset)

    @Property(str, notify=ReaderPropertiesMixin.changed)
    def scopeQuote(self):
        material = self.workbench.get_material(self._navigation.snapshot.browsing)
        return material.content[max(0, self.pendingEnd - 180) : self.pendingEnd] if material else ""

    @Slot()
    def markAllRead(self):
        material = self.workbench.get_material(self._navigation.snapshot.browsing)
        if material:
            self._reading.mark_end(material.id, len(material.content))
            self.changed.emit()

    @Slot(str)
    def locateSentence(self, sentence: str):
        material = self.workbench.get_material(self._navigation.snapshot.browsing)
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
        self._reading.mark_end(material.id, matches[0].end())
        self._reading.show_position(matches[0].start(), matches[0].end())
        self._navigation.error("")
        self.changed.emit()

    @Slot(float)
    def locatePercent(self, percent: float):
        material = self.workbench.get_material(self._navigation.snapshot.browsing)
        if material:
            end = paragraph_boundary(material.content, max(1, min(100, percent)))
            self._reading.mark_end(material.id, end)
            self._reading.show_position(max(0, end - 100), end)
            self.changed.emit()

    @Slot()
    def saveScope(self):
        material_id, end = self._navigation.snapshot.browsing, self.pendingEnd
        if self.vm.busy or not end:
            return

        async def operation(workbench=self.workbench):
            return workbench.set_reading_scope(end, material_id=material_id)

        def saved(_):
            if self._reading.scope_saved(material_id):
                self._imports.committed()
            self.vm.refresh_learning(ProjectionChange(scope=True))
            self.refresh()
            self.navigate("material")

        self.vm.run_operation(
            QCoreApplication.translate("Desktop", "正在保存已读范围…"), operation, saved
        )

    def begin_shutdown(self):
        self._navigation.close()
        self._imports.close()
        self._reading.close()
        self._jobs.close()
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
