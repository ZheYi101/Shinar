"""QML-facing application state for the desktop and mobile shells."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl, Qt, QCoreApplication, QTimer

from lingualoop.application import LearningWorkbench
from lingualoop.core import (
    LanguageEnum,
    MaterialSourceType,
    MaterialTrack,
    ProficiencyLevel,
    ReviewRating,
    ReviewStatus,
    PracticeOptions,
    PracticeMode,
    FeedbackTiming,
    CorrectionIntensity,
    SessionUserProfile,
)
from lingualoop.infrastructure.material_import import import_material_file
from lingualoop.core.reading_scope import scope_material, reading_end, paragraph_boundary
from lingualoop.kernel import SessionStepResult
from lingualoop.desktop.worker import AsyncWorker
from lingualoop.desktop.preferences import DesktopPreferences
from lingualoop.providers.speech import CompatibleSpeechProvider, SpeechSettings


AsyncOperation = Callable[[], Coroutine[Any, Any, Any]]


class LearningViewModel(QObject):
    """Small, stable QML API over :class:`LearningWorkbench`.

    Domain models stay in Python. QML receives plain strings and dictionaries so
    the UI is not coupled to Pydantic or LangGraph implementation details.
    """

    busyChanged = Signal()
    errorOccurred = Signal(str)
    statusChanged = Signal()
    materialChanged = Signal()
    sessionChanged = Signal()
    messagesChanged = Signal()
    feedbackItemsChanged = Signal()
    reviewItemsChanged = Signal()
    materialsChanged = Signal()
    dueReviewCountChanged = Signal()
    messageSent = Signal()
    uiChanged = Signal()
    topicsChanged = Signal()
    historyChanged = Signal()
    reviewReady = Signal()
    practiceStarted = Signal()

    def __init__(
        self,
        workbench: LearningWorkbench,
        provider_label: str,
        *,
        preferences=None,
        stt_provider=None,
        tts_provider=None,
        audio_controller=None,
    ) -> None:
        super().__init__()
        self._workbench = workbench
        self._provider_label = getattr(workbench._provider, "display_label", provider_label)
        self._busy = False
        self._status = QCoreApplication.translate("Desktop", "就绪。当前模式：{value0}").format(
            value0=self._provider_label
        )
        self._messages: list[dict[str, str]] = []
        self._feedback_items: list[dict[str, str]] = []
        self._review_items: list[dict[str, str]] = []
        self._worker = AsyncWorker(self)
        self._worker.completed.connect(
            self._operation_completed, Qt.ConnectionType.QueuedConnection
        )
        self._on_success = None
        self._retry_operation = None
        self._closed = False
        self._streaming_text = ""
        self._pending_user_text = ""
        self._response_timing = ""
        self._topic_filter = QCoreApplication.translate("Desktop", "全部")
        self._topic_search = ""
        self._preparation_state = "idle"
        self._analysis_identity = None
        self._preparation_timer = QTimer(self)
        self._preparation_timer.setInterval(250)
        self._preparation_timer.timeout.connect(self._poll_preparation)
        if QCoreApplication.instance() is not None:
            self._preparation_timer.start()
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is not None and hasattr(app, "styleHints"):
            app.styleHints().colorSchemeChanged.connect(lambda *_: self.uiChanged.emit())
        self._preferences = (
            preferences if preferences is not None else DesktopPreferences(parent=self)
        )
        self._error = ""
        self._draft = ""
        self._session_drafts = {}
        self.source_context_provider = lambda: None
        self._draft_revision = 0
        self._selected_topic = ""
        self._custom_topic = ""
        self._practice_mode = "discussion"
        self._role_description = ""
        self._recording_seconds = 0
        self._last_reply = ""
        self._stt = stt_provider
        self._tts = tts_provider
        self._local_speech = None
        speech_notes = []
        if "Mock" not in provider_label:
            for kind, attribute in (("STT", "_stt"), ("TTS", "_tts")):
                if getattr(self, attribute) is None:
                    try:
                        setattr(
                            self, attribute, CompatibleSpeechProvider(SpeechSettings.from_env(kind))
                        )
                    except ValueError:
                        speech_notes.append(
                            QCoreApplication.translate(
                                "Desktop",
                                "{value0} 未配置或配置无效，请检查 LINGUALOOP_{value1}_*。",
                            ).format(value0=kind, value1=kind)
                        )
        self._speech_status = "；".join(speech_notes) or (
            QCoreApplication.translate("Desktop", "识别与合成服务已配置，实际可用性需连接验证。")
            if self._stt and self._tts
            else QCoreApplication.translate("Desktop", "Mock 离线模式：语音服务未启用。")
        )
        self._audio = audio_controller
        if self._audio is None and QCoreApplication.instance() is not None:
            from lingualoop.desktop.audio import AudioController

            self._audio = AudioController(self)
        from lingualoop.desktop.voice import DesktopVoiceController

        self.voice = DesktopVoiceController(self)
        if workbench.session and workbench.session.topic:
            self._selected_topic = workbench.session.topic.id
        self._refresh_session_state()
        self._restore_last_reply()
        self._refresh_review_items()

    @Property(str, constant=True)
    def providerLabel(self) -> str:
        return self._provider_label

    @Property(dict, constant=True)
    def modelServices(self) -> dict[str, str]:
        settings = getattr(self._workbench._provider, "_settings", None)
        reasoning = getattr(settings, "reasoning_model", None)
        return {
            "reasoning": reasoning or self._provider_label,
            "dialogue": getattr(settings, "dialogue_model", None)
            or reasoning
            or self._provider_label,
        }

    @Property(list, notify=historyChanged)
    def sessionHistory(self):
        return [
            {
                "id": session.id,
                "title": session.topic.title
                if session.topic
                else QCoreApplication.translate("Desktop", "历史讨论"),
                "date": session.updated_at.astimezone().strftime("%m-%d %H:%M"),
                "status": QCoreApplication.translate("Desktop", "进行中")
                if session.status.value == "active"
                else QCoreApplication.translate("Desktop", "已结束"),
                "turns": sum(message.role.value == "user" for message in session.messages),
                "preview": next(
                    (
                        message.content[:140]
                        for message in session.messages
                        if message.role.value == "user"
                    ),
                    session.messages[0].content[:140] if session.messages else "",
                ),
                "selected": bool(
                    self._workbench.session and session.id == self._workbench.session.id
                ),
            }
            for session in self._workbench.sessions
        ]

    @Slot(str)
    def selectSession(self, session_id):
        if self.busy:
            return
        if self._workbench.session:
            self._session_drafts[self._workbench.session.id] = self._draft
        try:
            session = self._workbench.select_session(session_id)
        except ValueError as exc:
            self._on_operation_failed(str(exc))
            return
        self._clear_audio()
        self._selected_topic = session.topic.id if session.topic else ""
        self._draft = self._session_drafts.get(session.id, "")
        self._refresh_session_state()
        self._restore_last_reply()
        self._refresh_review_items()
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.messagesChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.topicsChanged.emit()
        self.historyChanged.emit()
        self.uiChanged.emit()

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy or self.voice.active

    @Property(bool, notify=busyChanged)
    def operationBusy(self) -> bool:
        return bool(self._busy or self.voice._job or self.voice.call.connectionState in
                    {"preparing", "connecting", "reconnecting", "stopping"})

    @Property(QObject, constant=True)
    def voiceController(self):
        return self.voice

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=materialChanged)
    def hasMaterial(self) -> bool:
        return self._workbench.material is not None

    @Property(str, notify=materialChanged)
    def selectedMaterialId(self):
        return self._workbench.material.id if self._workbench.material else ""

    @Property(bool, notify=sessionChanged)
    def hasSession(self) -> bool:
        return self._workbench.session is not None

    @Property(str, notify=materialChanged)
    def materialSummary(self) -> str:
        material = self._workbench.material
        if material is None:
            return QCoreApplication.translate("Desktop", "尚未加载材料。")
        if self._workbench.session and self._workbench.session.material_id == material.id:
            material = self._workbench._session_material()
        else:
            material = scope_material(material)
        names = {
            "japanese": QCoreApplication.translate("Desktop", "日语"),
            "english": QCoreApplication.translate("Desktop", "英语"),
            "chinese": QCoreApplication.translate("Desktop", "中文"),
            "french": QCoreApplication.translate("Desktop", "法语"),
            "germany": QCoreApplication.translate("Desktop", "德语"),
            "spanish": QCoreApplication.translate("Desktop", "西班牙语"),
        }
        lines = [
            QCoreApplication.translate("Desktop", "材料：{value0}").format(value0=material.title),
            QCoreApplication.translate("Desktop", "材料语言：{value0}").format(
                value0=names.get(material.source_language.value, material.source_language.value)
            ),
        ]
        if self._workbench.profile is not None:
            profile = self._workbench.profile
            lines.extend(
                [
                    QCoreApplication.translate("Desktop", "目标语言：{value0}").format(
                        value0=names.get(
                            profile.target_language.value, profile.target_language.value
                        )
                    ),
                    QCoreApplication.translate("Desktop", "学习等级：{value0}").format(
                        value0=profile.profile_level.value
                        if profile.profile_level.value != "unknown"
                        else "暂不确定"
                    ),
                ]
            )
        if material.analysis is not None:
            knowledge = material.analysis.knowledge
            summary = (
                (
                    knowledge.brief.summary
                    if knowledge.brief
                    else QCoreApplication.translate(
                        "Desktop", "基础理解尚未完成，已有原文可供聊天。"
                    )
                )
                if knowledge
                else material.analysis.summary
            )
            lines.append(
                QCoreApplication.translate("Desktop", "摘要：{value0}").format(value0=summary)
            )
            if material.analysis.keywords:
                lines.append(
                    QCoreApplication.translate("Desktop", "关键词：")
                    + "、".join(material.analysis.keywords)
                )
            if material.analysis.difficulties:
                lines.append(
                    QCoreApplication.translate("Desktop", "难点：")
                    + "、".join(material.analysis.difficulties)
                )
            if material.analysis.suggested_goals:
                lines.append(
                    QCoreApplication.translate("Desktop", "目标：")
                    + "；".join(material.analysis.suggested_goals)
                )
        return "\n".join(lines)

    @Property(str, notify=sessionChanged)
    def currentTask(self) -> str:
        session = self._workbench.session
        if session is None or session.current_instruction is None:
            return QCoreApplication.translate("Desktop", "尚未开始练习。")
        return session.current_instruction.prompt

    @Property(str, notify=sessionChanged)
    def sessionSummary(self) -> str:
        if self._workbench.session is None:
            return QCoreApplication.translate("Desktop", "尚未开始练习。")
        return "\n".join(self._workbench.session_lines())

    @Property(list, notify=messagesChanged)
    def messages(self) -> list[dict[str, str]]:
        return self._messages

    @Property(list, notify=feedbackItemsChanged)
    def feedbackItems(self) -> list[dict[str, str]]:
        return self._feedback_items

    @Property(list, notify=reviewItemsChanged)
    def reviewItems(self) -> list[dict[str, str]]:
        return self._review_items

    @Property(list, notify=materialsChanged)
    def materials(self) -> list[dict[str, str]]:
        return [
            {
                "id": item.id,
                "title": item.title,
                "sourceType": item.source_type.value,
                "sourcePath": item.source_path or "",
            }
            for item in self._workbench.materials
        ]

    @Property(int, notify=dueReviewCountChanged)
    def dueReviewCount(self) -> int:
        return self._workbench.due_review_count

    @Property(str, notify=materialChanged)
    def materialTitle(self) -> str:
        return self._workbench.material.title if self._workbench.material else ""

    @Property(str, notify=materialChanged)
    def materialContent(self) -> str:
        if self._workbench.material is None:
            return ""
        return scope_material(self._workbench.material).content

    @Property(str, notify=materialChanged)
    def analysisSummary(self):
        material = self._workbench.material
        material = scope_material(material) if material else None
        if material and material.analysis and material.analysis.knowledge:
            knowledge = material.analysis.knowledge
            return (
                knowledge.brief.summary
                if knowledge.brief
                else QCoreApplication.translate(
                    "Desktop", "基础理解尚未完成，可查看已保存的局部笔记并先开始聊天。"
                )
            )
        return (
            material.analysis.summary
            if material and material.analysis
            else QCoreApplication.translate("Desktop", "先确认读到哪里，然后随时开聊。")
        )

    @Property(list, notify=materialChanged)
    def analysisOutline(self):
        analysis = (
            scope_material(self._workbench.material).analysis if self._workbench.material else None
        )
        if analysis and analysis.knowledge:
            if analysis.knowledge.brief:
                return [point.text for point in analysis.knowledge.brief.points]
            return [
                note.text
                for note in analysis.knowledge.notes[:12]
                if note.source_kind not in {"foreword", "author_note", "commentary"}
            ]
        return list(getattr(analysis, "outline", []))

    @Property(list, notify=materialChanged)
    def analysisCharacters(self):
        analysis = (
            scope_material(self._workbench.material).analysis if self._workbench.material else None
        )
        return [item.model_dump() for item in getattr(analysis, "characters", [])]

    @Property(bool, notify=materialChanged)
    def materialPrepared(self):
        material = self._workbench.material
        return bool(
            material
            and material.analysis
            and getattr(material.analysis, "preparation_complete", True)
        )

    @Property(str, notify=materialChanged)
    def materialPreparation(self):
        material = self._workbench.material
        if not material:
            return QCoreApplication.translate("Desktop", "尚未导入")
        analysis = material.analysis
        if analysis and analysis.knowledge:
            knowledge = analysis.knowledge
            count = len(knowledge.completed_unit_ids)
            total = len(knowledge.units) - len(knowledge.excluded_unit_ids)
            label = {
                "saved": QCoreApplication.translate("Desktop", "基础理解待开始"),
                "preparing": QCoreApplication.translate("Desktop", "正在理解已读内容"),
                "partial": QCoreApplication.translate("Desktop", "基础理解尚未完成"),
                "ready": QCoreApplication.translate("Desktop", "基础理解与概述已保存"),
                "failed": QCoreApplication.translate("Desktop", "基础理解暂未完成"),
            }[knowledge.status]
            auxiliary = (
                QCoreApplication.translate("Desktop", " · {value0} 段附属资料独立保留").format(
                    value0=len(knowledge.excluded_unit_ids)
                )
                if knowledge.excluded_unit_ids
                else ""
            )
            return (
                QCoreApplication.translate(
                    "Desktop", "{value0} · {value1}/{value2} 段 · {value3} 条有出处笔记"
                ).format(value0=label, value1=count, value2=total, value3=len(knowledge.notes))
                + auxiliary
            )
        if analysis and not getattr(analysis, "preparation_complete", True):
            chunks = getattr(analysis, "chunks", [])
            if sum(chunk.end_char - chunk.start_char for chunk in chunks) == len(material.content):
                return (
                    QCoreApplication.translate("Desktop", "各段已保存，正在汇总整书概要和话题…")
                    if self._workbench.is_analyzing
                    else QCoreApplication.translate(
                        "Desktop", "各段已保存，继续完成整书汇总后可开聊"
                    )
                )
            return QCoreApplication.translate("Desktop", "已整理并保存 {value0} 段").format(
                value0=len(chunks)
            ) + (
                QCoreApplication.translate("Desktop", "，正在继续…")
                if self.busy
                else QCoreApplication.translate("Desktop", "，继续分析后可开聊")
            )
        if material.read_through == 0:
            return QCoreApplication.translate("Desktop", "原文已保存在本机 · 请确认已读范围")
        if analysis and analysis.preparation_strategy == "source-index-v1":
            return QCoreApplication.translate(
                "Desktop", "已建立 {value0} 段本地引用 · 未调用 AI 生成题库"
            ).format(value0=len(analysis.chunks))
        return (
            QCoreApplication.translate("Desktop", "已有整理资料可供聊天参考")
            if analysis
            else QCoreApplication.translate("Desktop", "原文已保存，确认范围即可开聊")
        )

    @Property(str, notify=materialChanged)
    def materialRawContent(self) -> str:
        if self._workbench.material is None:
            return ""
        return scope_material(self._workbench.material).content

    @Property(str, notify=materialChanged)
    def materialNormalizedContent(self) -> str:
        if self._workbench.material is None:
            return ""
        return scope_material(self._workbench.material).content

    @Slot(str, str, str, str, str, str)
    def loadMaterial(
        self,
        title: str,
        content: str,
        source_language: str,
        target_language: str,
        native_language: str,
        learner_level: str,
    ) -> None:
        if self.busy:
            return
        if not title.strip() or not content.strip():
            self.errorOccurred.emit(
                QCoreApplication.translate("Desktop", "请填写材料标题和材料内容。")
            )
            return

        self._clear_audio()
        self._draft = ""

        async def operation() -> Any:
            return await self._workbench.load_material(
                title=title,
                content=content,
                source_language=LanguageEnum(source_language),
                target_language=LanguageEnum(target_language),
                native_language=LanguageEnum(native_language),
                learner_level=ProficiencyLevel(learner_level),
                source_type=MaterialSourceType.TEXT,
                auto_prepare=False,
            )

        self._run_operation(
            QCoreApplication.translate("Desktop", "正在保存材料..."),
            operation,
            self._after_material_loaded,
        )

    @Slot(str, str, str, str, str, str, str)
    def importMaterial(
        self,
        path_text: str,
        title: str,
        source_language: str,
        target_language: str,
        native_language: str,
        learner_level: str,
        track: str,
    ) -> None:
        if self.busy:
            return
        try:
            imported = import_material_file(_local_path(path_text) or Path(path_text))
        except Exception as exc:  # noqa: BLE001 - user-facing import error
            self.errorOccurred.emit(
                QCoreApplication.translate("Desktop", "导入失败：{value0}").format(value0=exc)
            )
            return

        self._clear_audio()
        self._draft = ""

        async def operation() -> Any:
            return await self._workbench.load_imported_material(
                imported,
                title=title.strip() or None,
                source_language=LanguageEnum(source_language),
                target_language=LanguageEnum(target_language),
                native_language=LanguageEnum(native_language),
                learner_level=ProficiencyLevel(learner_level),
                track=MaterialTrack(track),
                auto_prepare=False,
            )

        self._run_operation(
            QCoreApplication.translate("Desktop", "正在导入材料..."),
            operation,
            self._after_material_loaded,
        )

    @Slot()
    def startPractice(self) -> None:
        if self.busy:
            return
        options = PracticeOptions(
            mode=PracticeMode(self._practice_mode),
            difficulty=ProficiencyLevel(self._preferences.difficulty),
            correction_intensity=CorrectionIntensity(self._preferences.correctionIntensity),
            feedback_timing=FeedbackTiming(self._preferences.feedbackTiming),
            role_description=self._role_description,
        )
        profile = self._selected_profile()
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在开始对话…"),
            lambda: self._workbench.start_session(
                topic_id=None, custom_topic=None, options=options, profile=profile
            ),
            self._after_started,
        )

    @Slot(str)
    def sendMessage(self, content: str) -> None:
        self.voice.send_text(content)

    @Slot()
    def finishPractice(self) -> None:
        if self.busy:
            return
        self._clear_audio()
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在生成复盘..."),
            self._workbench.complete_session,
            self._after_completed,
        )

    @Slot(str, str, str)
    def reviewOutcome(self, review_id: str, rating: str, answer: str) -> None:
        try:
            review_rating = ReviewRating(rating)
        except ValueError:
            self.errorOccurred.emit(QCoreApplication.translate("Desktop", "无效的复习结果。"))
            return
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在保存复习结果..."),
            lambda: self._workbench.record_review_outcome(review_id, review_rating, answer or None),
            lambda _outcome: self._after_review_changed(),
        )

    @Slot(str, str)
    def updateReviewStatus(self, review_id: str, status: str) -> None:
        try:
            review_status = ReviewStatus(status)
        except ValueError:
            self.errorOccurred.emit(QCoreApplication.translate("Desktop", "无效的复习状态。"))
            return
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在更新复习项..."),
            lambda: self._workbench.update_review_status(review_id, review_status),
            lambda _result: self._after_review_changed(),
        )

    @Slot(str)
    def selectMaterial(self, material_id: str) -> None:
        if self.busy:
            self._on_operation_failed(QCoreApplication.translate("Desktop", "请等待当前操作完成。"))
            return
        self._clear_audio()
        try:
            self._workbench.select_material(material_id)
        except Exception as exc:  # noqa: BLE001 - forwarded to UI
            self.errorOccurred.emit(str(exc))
            return
        self._selected_topic = ""
        self._custom_topic = ""
        self._topic_filter = QCoreApplication.translate("Desktop", "全部")
        self._topic_search = ""
        self._draft = ""
        self._refresh_session_state()
        self._restore_last_reply()
        self._refresh_review_items()
        self.topicsChanged.emit()
        self.uiChanged.emit()
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.messagesChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.dueReviewCountChanged.emit()

        self.historyChanged.emit()

    @Slot(str)
    def exportSession(self, path_text: str) -> None:
        path = _local_path(path_text)
        if path is None:
            self.errorOccurred.emit(QCoreApplication.translate("Desktop", "请选择导出文件。"))
            return
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在导出会话..."),
            lambda: self._workbench.export_json(path),
            lambda exported: self._set_status(
                QCoreApplication.translate("Desktop", "已导出到 {value0}").format(value0=exported)
            ),
        )

    @Slot()
    def resetSession(self) -> None:
        if self.busy:
            self.errorOccurred.emit(QCoreApplication.translate("Desktop", "当前还有操作正在运行。"))
            return
        self._clear_audio()
        self._draft = ""
        self._selected_topic = ""
        self._custom_topic = ""
        self._workbench.reset()
        self.historyChanged.emit()
        self._messages = []
        self._feedback_items = []
        self._review_items = []
        self._set_status(
            QCoreApplication.translate("Desktop", "状态已重置。当前模式：{value0}").format(
                value0=self._provider_label
            )
        )
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.messagesChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.materialsChanged.emit()
        self.dueReviewCountChanged.emit()

    def _run_operation(
        self,
        status: str,
        operation: AsyncOperation,
        on_success: Callable[[Any], None],
    ) -> None:
        if self.busy:
            self.errorOccurred.emit(QCoreApplication.translate("Desktop", "当前还有操作正在运行。"))
            return
        self._busy = True
        self.busyChanged.emit()
        self._set_status(status)

        self._on_success = on_success
        self._retry_operation = (status, operation, on_success)
        self._error = ""
        self.uiChanged.emit()
        try:
            self._worker.submit(operation)
        except RuntimeError:
            self._operation_completed(
                None,
                QCoreApplication.translate("Desktop", "后台任务启动失败，请重试或重新启动应用。"),
            )

    @Slot(object, str)
    def _operation_completed(self, result, error):
        if self._closed:
            return
        callback = self._on_success
        self._on_success = None
        self._busy = False
        self.busyChanged.emit()
        if error:
            self._streaming_text = ""
            self._pending_user_text = ""
            self._on_operation_failed(error)
            self._refresh_session_state()
            self.materialChanged.emit()
            self.materialsChanged.emit()
            self.topicsChanged.emit()
            self.messagesChanged.emit()
        elif callback is not None:
            self._error = ""
            self._retry_operation = None
            callback(result)
        self.uiChanged.emit()

    @Slot(str)
    def _on_operation_failed(self, message):
        self._error = message
        self.errorOccurred.emit(message)
        self._set_status(QCoreApplication.translate("Desktop", "操作未完成，内容已保留。"))

    def _after_material_loaded(self, _material: Any) -> None:
        self._refresh_session_state()
        self._selected_topic = ""
        self._topic_filter = QCoreApplication.translate("Desktop", "全部")
        self._topic_search = ""
        self._refresh_review_items()
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.messagesChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.materialsChanged.emit()
        self.dueReviewCountChanged.emit()
        self.topicsChanged.emit()
        self.historyChanged.emit()
        if not self._error:
            self._set_status(
                QCoreApplication.translate(
                    "Desktop", "范围已确认，可以先聊天，基础理解会在后台保存。"
                )
                if self.readingScopeConfirmed
                else QCoreApplication.translate("Desktop", "材料已保存，请确认已读范围。")
            )

    def _after_completed(self, result):
        self._after_session_changed(result)
        self.reviewReady.emit()

    def _restore_last_reply(self):
        self._last_reply = next(
            (
                message["content"]
                for message in reversed(self._messages)
                if message["role"] == "assistant"
            ),
            "",
        )

    def _after_session_changed(self, result: SessionStepResult) -> None:
        session = result.session
        self._refresh_session_state(session)
        self._refresh_review_items()
        self.sessionChanged.emit()
        self.messagesChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.dueReviewCountChanged.emit()
        self.historyChanged.emit()
        self._set_status(QCoreApplication.translate("Desktop", "练习已更新。"))

    def _after_review_changed(self) -> None:
        self._refresh_review_items()
        self.reviewItemsChanged.emit()
        self.dueReviewCountChanged.emit()
        self._set_status(QCoreApplication.translate("Desktop", "复习结果已保存。"))

    def _refresh_review_items(self) -> None:
        self._review_items = self._review_dtos(self._workbench.review_queue)

    def _refresh_session_state(self, session: Any | None = None) -> None:
        session = session or self._workbench.session
        if session is None:
            self._messages = []
            self._feedback_items = []
            return
        turn_id = ""
        messages = []
        for message in session.messages:
            if message.role.value == "user":
                turn_id = message.metadata.get("turn_id", "")
            messages.append({
                **self.voice.turn_details(message, turn_id),
                "id": message.id,
                "role": message.role.value,
                "content": message.content,
                "source": message.source_context.model_dump(mode="json")
                if message.source_context
                else None,
            })
        self._messages = messages
        self._feedback_items = [
            {
                "original": item.original,
                "corrected": item.corrected,
                "explanation": item.explanation,
            }
            for item in session.feedback_items
        ]

    @staticmethod
    def _review_dtos(items: list[Any]) -> list[dict[str, str]]:
        return [
            {
                "id": item.id,
                "prompt": item.prompt,
                "answer": item.answer,
                "context": item.context or "",
                "dueAt": item.due_at.isoformat() if item.due_at else "",
            }
            for item in items
        ]

    def _set_status(self, value: str) -> None:
        self._status = value
        self.statusChanged.emit()

    @Property(QObject, constant=True)
    def preferences(self):
        return self._preferences

    @Property(bool, notify=uiChanged)
    def systemDark(self):
        from PySide6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        return bool(
            app
            and hasattr(app, "styleHints")
            and app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        )

    @Property(str, notify=uiChanged)
    def errorMessage(self):
        return self._error

    @Property(bool, notify=uiChanged)
    def canRetryOperation(self):
        return bool(self._retry_operation)

    @Property(str, notify=uiChanged)
    def draft(self):
        return self._draft

    @draft.setter
    def draft(self, value):
        if value != self._draft:
            self._draft_revision += 1
            self._draft = value
            self.uiChanged.emit()

    @Property(str, notify=uiChanged)
    def customTopic(self):
        return self._custom_topic

    @customTopic.setter
    def customTopic(self, value):
        self._custom_topic = value
        self.uiChanged.emit()

    @Property(str, notify=uiChanged)
    def practiceMode(self):
        return self._practice_mode

    @practiceMode.setter
    def practiceMode(self, value):
        if value in {"discussion", "roleplay"}:
            self._practice_mode = value
            self.uiChanged.emit()

    @Property(str, notify=uiChanged)
    def roleDescription(self):
        return self._role_description

    @roleDescription.setter
    def roleDescription(self, value):
        self._role_description = value
        self.uiChanged.emit()

    @Property(str, notify=uiChanged)
    def selectedTopicId(self):
        return self._selected_topic

    @Property(list, notify=topicsChanged)
    def topics(self):
        material = self._workbench.material
        material = scope_material(material) if material else None
        return (
            [
                dict(topic.model_dump(), category_label=_topic_category_label(topic.category))
                for topic in material.analysis.topics
            ]
            if material and material.analysis
            else []
        )

    @Property(list, notify=topicsChanged)
    def topicCategories(self):
        return [
            QCoreApplication.translate("Desktop", "全部"),
            *dict.fromkeys(topic["category_label"] for topic in self.topics),
        ]

    @Property(str, notify=topicsChanged)
    def topicFilter(self):
        return self._topic_filter

    @topicFilter.setter
    def topicFilter(self, value):
        self._topic_filter = value
        self.topicsChanged.emit()

    @Property(list, notify=topicsChanged)
    def filteredTopics(self):
        return [
            topic
            for topic in self.topics
            if (
                self._topic_filter == QCoreApplication.translate("Desktop", "全部")
                or topic["category_label"] == self._topic_filter
            )
            and self._topic_search.casefold()
            in (topic["title"] + " " + topic["opening_question"]).casefold()
        ]

    @Property(str, notify=topicsChanged)
    def topicSearch(self):
        return self._topic_search

    @topicSearch.setter
    def topicSearch(self, value):
        self._topic_search = value.strip()
        self.topicsChanged.emit()

    @Property(str, notify=uiChanged)
    def selectedTopicTitle(self):
        return next(
            (topic["title"] for topic in self.topics if topic["id"] == self._selected_topic),
            QCoreApplication.translate("Desktop", "随便聊聊，不用先选话题"),
        )

    @Property(str, notify=uiChanged)
    def streamingText(self):
        return self._streaming_text

    @Property(str, notify=uiChanged)
    def pendingUserText(self):
        return self._pending_user_text

    @Property(str, notify=uiChanged)
    def responseTiming(self):
        return self._response_timing

    @Property(str, notify=uiChanged)
    def preparationStatus(self):
        return {
            "idle": "",
            "preparing": QCoreApplication.translate("Desktop", "正在后台准备下一轮参考…"),
            "ready": QCoreApplication.translate("Desktop", "下一轮参考已准备"),
            "unavailable": QCoreApplication.translate("Desktop", "后台准备暂不可用，对话仍可继续"),
        }.get(self._preparation_state, "")

    @Slot()
    def _poll_preparation(self):
        state = getattr(self._workbench, "preparation_status", "idle")
        if state != self._preparation_state:
            self._preparation_state = state
            self.uiChanged.emit()
        material = self._workbench.material
        identity = (material.id, id(material.analysis)) if material else None
        if identity != self._analysis_identity:
            self._analysis_identity = identity
            self.materialChanged.emit()
            self.topicsChanged.emit()

    @Property(str, notify=sessionChanged)
    def topicTitle(self):
        session = self._workbench.session
        return (
            session.topic.title
            if session and session.topic
            else QCoreApplication.translate("Desktop", "随便聊聊")
        )

    @Property(bool, notify=sessionChanged)
    def sessionActive(self):
        return (
            self._workbench.session is not None and self._workbench.session.status.value == "active"
        )

    @Property(bool, notify=uiChanged)
    def voiceReady(self):
        return bool(
            self._speech_available("stt")
            and self._audio is not None
        )

    @Property(str, notify=uiChanged)
    def speechStatus(self):
        return self._speech_status

    @Property(str, notify=uiChanged)
    def voiceState(self):
        return self.voice.legacy_state

    @Property(int, notify=uiChanged)
    def recordingSeconds(self):
        return self._recording_seconds

    @Property(list, notify=uiChanged)
    def inputDevices(self):
        return self._audio.input_devices if self._audio else []

    @Property(list, notify=uiChanged)
    def outputDevices(self):
        return self._audio.output_devices if self._audio else []

    @Property(str, notify=uiChanged)
    def selectedInputDeviceId(self):
        return getattr(self._audio, "selected_input_id", self.inputDevices[0]["id"] if self.inputDevices else "")

    @Property(str, notify=uiChanged)
    def selectedOutputDeviceId(self):
        return getattr(self._audio, "selected_output_id", self.outputDevices[0]["id"] if self.outputDevices else "")

    @Property(bool, notify=uiChanged)
    def canRetryTranscription(self):
        return self.voice.canRetryTranscription

    @Property(bool, notify=uiChanged)
    def canSpeak(self):
        return bool(self._last_reply and self._speech_available("tts"))

    def configure_local_speech(self, library):
        self._local_speech = library.local_service
        library.configure_preview(lambda: self.selectedOutputDeviceId, lambda: self.voice.active)
        library.inferenceStatus.connect(self._local_speech_status)
        library.configurationChanged.connect(self._local_speech_configuration)

    @Slot()
    def _local_speech_configuration(self):
        self.voice.invalidate_cache()
        self.uiChanged.emit()

    @Slot(str)
    def _local_speech_status(self, value):
        self._speech_status = value
        self.uiChanged.emit()

    def _speech_available(self, task):
        return bool(
            (self._local_speech and self._local_speech.enabled(task)) or getattr(self, "_" + task)
        )

    def _speech_language(self):
        session = self._workbench.session
        language = (
            session.profile.target_language.value if session else self._preferences.targetLanguage
        )
        return {
            "japanese": "ja",
            "english": "en",
            "chinese": "zh",
            "korean": "ko",
            "french": "fr",
            "germany": "de",
            "spanish": "es",
        }.get(language, language)

    def _speech_operation(self, task, content):
        # Resolve the real session's language on the GUI thread; library filters are unrelated.
        if self._local_speech and self._local_speech.enabled(task):
            language = self._speech_language()
            method = (
                self._local_speech.transcribe if task == "stt" else self._local_speech.synthesize
            )
            return lambda: method(content, language)
        provider = getattr(self, "_" + task)
        method = provider.transcribe if task == "stt" else provider.synthesize
        return lambda: method(content)

    @Property(str, notify=sessionChanged)
    def reviewSummary(self):
        session = self._workbench.session
        return (
            session.review.summary
            if session and session.review
            else QCoreApplication.translate("Desktop", "对话结束后，这里会显示本轮总结。")
        )

    @Property(bool, notify=materialChanged)
    def readingScopeConfirmed(self):
        return bool(self._workbench.material and reading_end(self._workbench.material) > 0)

    @Property(str, notify=materialChanged)
    def readingScopeLabel(self):
        material = self._workbench.material
        if not material or material.read_through == 0:
            return QCoreApplication.translate("Desktop", "尚未确认已读范围")
        end = reading_end(material)
        return (
            QCoreApplication.translate("Desktop", "已读完本份材料")
            if end == len(material.content)
            else QCoreApplication.translate(
                "Desktop", "只聊已读部分 · 原文约 {value0:.1f}%"
            ).format(value0=100 * end / len(material.content))
        )

    @Slot(int, result=str)
    def readingPreview(self, percent):
        material = self._workbench.material
        if not material:
            return ""
        end = paragraph_boundary(material.content, percent)
        return material.content[max(0, end - 240) : end].strip()

    @Slot(int)
    def confirmReadingPercent(self, percent):
        if self.busy or not self._workbench.material:
            return
        end = paragraph_boundary(self._workbench.material.content, percent)
        self._confirm_scope(end)

    @Slot(str)
    def confirmReadingPassage(self, passage):
        if self.busy or not self._workbench.material:
            return
        text = self._workbench.material.content
        passage = passage.strip()
        if len(passage) < 8 or text.count(passage) != 1:
            self.errorOccurred.emit(
                QCoreApplication.translate(
                    "Desktop", "请粘贴原文中唯一的一句（至少 8 个字符），以便精确确定已读位置。"
                )
            )
            return
        self._confirm_scope(text.index(passage) + len(passage))

    def _confirm_scope(self, end):
        async def operation():
            return self._workbench.set_reading_scope(end)

        self._run_operation(
            QCoreApplication.translate("Desktop", "正在建立本地引用…"),
            operation,
            self._after_material_loaded,
        )

    @Property(bool, notify=materialChanged)
    def canResumeMaterialPreparation(self):
        material = self._workbench.material
        knowledge = material.analysis.knowledge if material and material.analysis else None
        return bool(knowledge and knowledge.status in {"saved", "partial", "failed"})

    @Slot()
    def resumeMaterialPreparation(self):
        if not self._busy:

            async def operation():
                return self._workbench.resume_material_preparation()

            self._run_operation(
                QCoreApplication.translate("Desktop", "正在继续基础理解…"),
                operation,
                self._after_material_loaded,
            )

    @Property(list, notify=uiChanged)
    def suggestedDirections(self):
        session = self._workbench.session
        if session and session.focus_reference:
            if session.focus_reference.based_on_message_ids == [
                message.id for message in session.messages
            ]:
                return session.focus_reference.directions[:2]
            return []
        if (
            not session
            or not session.preparation
            or session.preparation.based_on_message_count != len(session.messages)
        ):
            return []
        if sum(message.role.value == "user" for message in session.messages) < 2:
            return []
        return session.preparation.suggested_directions[:3]

    @Slot(str)
    def useDirection(self, direction):
        if direction in self.suggestedDirections:
            self.draft = direction

    @Slot(str)
    def selectTopic(self, topic_id):
        if self.busy:
            return
        self._selected_topic = topic_id
        self._custom_topic = ""
        self.uiChanged.emit()

    @Slot()
    def reanalyze(self):
        profile = self._selected_profile()
        self._run_operation(
            QCoreApplication.translate("Desktop", "正在重新分析..."),
            lambda: self._workbench.analyze_current_material(profile=profile),
            self._after_material_loaded,
        )

    def _selected_profile(self):
        return SessionUserProfile(
            profile_level=ProficiencyLevel(self._preferences.difficulty),
            native_language=LanguageEnum(self._preferences.nativeLanguage),
            target_language=LanguageEnum(self._preferences.targetLanguage),
        )

    @Slot()
    def retryOperation(self):
        if self.busy:
            return
        if self._retry_operation:
            if self._workbench.material and self._workbench.material.analysis is None:
                self.reanalyze()
            else:
                self._run_operation(*self._retry_operation)

    @Slot()
    def dismissError(self):
        self._error = ""
        self.uiChanged.emit()

    def _after_started(self, result):
        self._draft = self._custom_topic.strip()
        self._custom_topic = ""
        if result.session.topic:
            self._selected_topic = result.session.topic.id
        self.topicsChanged.emit()
        self.materialChanged.emit()
        self.uiChanged.emit()
        self._after_session_changed(result)
        self._last_reply = result.assistant_message.content if result.assistant_message else ""
        self.practiceStarted.emit()
        if self.preferences.autoReadReplies and self._speech_available("tts"):
            self.speakReply()

    @Slot()
    def startRecording(self):
        self.voice.startRecording()

    @Slot()
    def stopRecording(self):
        self.voice.stopRecording()

    @Slot()
    def cancelRecording(self):
        self.voice.cancelRecording()

    @Slot()
    def rerecord(self):
        self.voice.discardRecording()
        self.voice.startRecording()

    @Slot()
    def retryTranscription(self):
        self.voice.retryTranscription()

    @Slot()
    def speakReply(self):
        self.voice.speak_latest()

    @Slot()
    def stopPlayback(self):
        self.voice.stopPlayback()

    @Slot(str, bool)
    def selectAudioDevice(self, device_id, output):
        if self.voice.call.active:
            self.voice.call.device_changed()
        if self._audio and (not self.busy or self.voice.call.active):
            self._audio.select_device(device_id, output=output)

    def _clear_audio(self):
        self.voice.reset()
        if self._audio:
            self._audio.clear()
        self._last_reply = ""
        self._retry_operation = None
        self.uiChanged.emit()

    @Slot()
    def close(self):
        if not self._closed:
            self._closed = True
            self.voice.close()
            self._preparation_timer.stop()

            async def cleanup():
                try:
                    await self.voice.call.aclose()
                finally:
                    try:
                        if self._local_speech:
                            await self._local_speech.close()
                    finally:
                        await self._workbench.aclose()

            self._worker.close(cleanup)
            self._clear_audio()


def _topic_category_label(category: str) -> str:
    value = (category or "").strip().casefold()
    # Providers use many near-synonyms. Keep the browsing vocabulary finite;
    # retain the original category in the topic payload for export and search.
    groups = (
        ("自定义", ("custom", "自定义")),
        (
            "叙述与文体",
            (
                "narrat",
                "reliab",
                "voice",
                "prose",
                "style",
                "author",
                "editor",
                "critici",
                "叙述",
                "叙事",
                "文体",
                "作者",
                "评论",
            ),
        ),
        ("人物关系", ("relation", "family", "power", "relationship", "关系", "家庭", "权力")),
        ("人物", ("character", "motiv", "choice", "人物", "角色", "动机", "选择")),
        (
            "故事与情节",
            (
                "story",
                "plot",
                "event",
                "travel",
                "setting",
                "reversal",
                "ending",
                "mystery",
                "故事",
                "情节",
                "结局",
                "反转",
            ),
        ),
        (
            "作品主题",
            ("theme", "moral", "ethic", "guilt", "responsib", "主题", "道德", "罪责", "责任"),
        ),
        (
            "感受与经历",
            ("impression", "emotion", "feeling", "memory", "experience", "感受", "经历", "体验"),
        ),
    )
    return next(
        (label for label, terms in groups if any(term in value for term in terms)), "综合讨论"
    )


def _local_path(value: str) -> Path | None:
    if not value.strip():
        return None
    url = QUrl(value)
    if url.isValid() and url.isLocalFile():
        return Path(url.toLocalFile())
    return Path(value).expanduser()
