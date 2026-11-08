"""QML-facing application state for the desktop and mobile shells."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Property, Slot, QUrl, Qt, QCoreApplication, QTimer

from shinar.application import LearningWorkbench
from shinar.core import (
    LanguageEnum,
    ProficiencyLevel,
    ReviewRating,
    ReviewStatus,
    SessionUserProfile,
)
from shinar.core.reading_scope import paragraph_boundary
from shinar.kernel import SessionStepResult
from shinar.desktop.tasks.worker import AsyncWorker
from shinar.desktop.presentation.conversation_presentation import ConversationEvent, ConversationPresentation
from shinar.desktop.presentation.conversation_view import ConversationViewMixin
from shinar.desktop.shell.preferences import DesktopPreferences
from shinar.providers.speech import CompatibleSpeechProvider, SpeechSettings


from shinar.desktop.presentation.properties import (LearningPropertiesMixin, topic_category_label as topic_category_label)

AsyncOperation = Callable[[], Coroutine[Any, Any, Any]]


class LearningViewModel(QObject, LearningPropertiesMixin, ConversationViewMixin):
    """Small, stable QML API over :class:`LearningWorkbench`.

    Domain models stay in Python. QML receives plain strings and dictionaries so
    the UI is not coupled to Pydantic or LangGraph implementation details.
    """



    workbench = property(lambda self: self._workbench)
    worker = property(lambda self: self._worker)
    audio = property(lambda self: self._audio)
    local_speech = property(lambda self: self._local_speech)
    draft_revision = property(lambda self: self._draft_revision)

    def speech_provider(self, task: str):
        return self._stt if task == "stt" else self._tts

    def remember_draft(self) -> None:
        if self._workbench.session:
            self._session_drafts[self._workbench.session.id] = self.draft

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
        self._conversation = ConversationPresentation()
        self._presentation_generation = 0
        self._workbench = workbench
        self._provider_label = getattr(workbench.provider, "display_label", provider_label)
        self._busy = False
        self._status = QCoreApplication.translate("Desktop", "就绪。当前模式：{value0}").format(
            value0=self._provider_label
        )
        self._feedback_items: list[dict[str, str]] = []
        self._review_items: list[dict[str, str]] = []
        self._worker = AsyncWorker(self)
        self._worker.completed.connect(
            self._operation_completed, Qt.ConnectionType.QueuedConnection
        )
        self._on_success = None
        self._retry_operation = None
        self._closed = False
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
        self._draft = ""
        self._session_drafts = {}
        self.source_context_provider = lambda: None
        self._draft_revision = 0
        self._selected_topic = ""
        self._custom_topic = ""
        self._practice_mode = "discussion"
        self._role_description = ""
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
                                "{value0} 未配置或配置无效，请检查 SHINAR_{value1}_*。",
                            ).format(value0=kind, value1=kind)
                        )
        self._speech_status = "；".join(speech_notes) or (
            QCoreApplication.translate("Desktop", "识别与合成服务已配置，实际可用性需连接验证。")
            if self._stt and self._tts
            else QCoreApplication.translate("Desktop", "Mock 离线模式：语音服务未启用。")
        )
        self._audio = audio_controller
        if self._audio is None and QCoreApplication.instance() is not None:
            from shinar.desktop.voice.audio import AudioController

            self._audio = AudioController(self)
        from shinar.desktop.voice.turns import DesktopVoiceController

        self.voice = DesktopVoiceController(self)
        if workbench.session and workbench.session.topic:
            self._selected_topic = workbench.session.topic.id
        self.refresh_session_state()
        self.restore_last_reply()
        self._refresh_review_items()


    @Slot(str)
    def selectSession(self, session_id):
        if self.busy:
            return
        if self._workbench.session:
            self._session_drafts[self._workbench.session.id] = self._draft
        try:
            session = self._workbench.select_session(session_id)
        except ValueError as exc:
            self.report_error(str(exc))
            return
        self._clear_audio()
        self._selected_topic = session.topic.id if session.topic else ""
        self._draft = self._session_drafts.get(session.id, "")
        self.refresh_session_state()
        self.restore_last_reply()
        self._refresh_review_items()
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.topicsChanged.emit()
        self.historyChanged.emit()
        self.uiChanged.emit()


    @Property(QObject, constant=True)
    def voiceController(self):
        return self.voice


    @Slot(str)
    def sendMessage(self, content: str) -> None:
        self.voice.send_text(content)

    @Slot()
    def finishPractice(self) -> None:
        if self.busy:
            return
        self._clear_audio()
        self.run_operation(
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
        self.run_operation(
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
        self.run_operation(
            QCoreApplication.translate("Desktop", "正在更新复习项..."),
            lambda: self._workbench.update_review_status(review_id, review_status),
            lambda _result: self._after_review_changed(),
        )

    @Slot(str)
    def selectMaterial(self, material_id: str) -> None:
        if self.busy:
            self.report_error(QCoreApplication.translate("Desktop", "请等待当前操作完成。"))
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
        self.refresh_session_state()
        self.restore_last_reply()
        self._refresh_review_items()
        self.topicsChanged.emit()
        self.uiChanged.emit()
        self.materialChanged.emit()
        self.sessionChanged.emit()
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
        self.run_operation(
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
        self.refresh_session_state()
        self._feedback_items = []
        self._review_items = []
        self._set_status(
            QCoreApplication.translate("Desktop", "状态已重置。当前模式：{value0}").format(
                value0=self._provider_label
            )
        )
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.materialsChanged.emit()
        self.dueReviewCountChanged.emit()

    def run_operation(
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
        self.present_conversation(ConversationEvent("error"))
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
            self.present_conversation(ConversationEvent("invalidate"))
            self.report_error(error)
            self.refresh_session_state()
            self.materialChanged.emit()
            self.materialsChanged.emit()
            self.topicsChanged.emit()
        elif callback is not None:
            self.present_conversation(ConversationEvent("error"))
            self._retry_operation = None
            callback(result)
        self.uiChanged.emit()

    @Slot(str)
    def report_error(self, message):
        self.present_conversation(ConversationEvent("error", text=message))
        self.errorOccurred.emit(message)
        self._set_status(QCoreApplication.translate("Desktop", "操作未完成，内容已保留。"))

    def _after_material_loaded(self, _material: Any) -> None:
        self.refresh_session_state()
        self._selected_topic = ""
        self._topic_filter = QCoreApplication.translate("Desktop", "全部")
        self._topic_search = ""
        self._refresh_review_items()
        self.materialChanged.emit()
        self.sessionChanged.emit()
        self.feedbackItemsChanged.emit()
        self.reviewItemsChanged.emit()
        self.materialsChanged.emit()
        self.dueReviewCountChanged.emit()
        self.topicsChanged.emit()
        self.historyChanged.emit()
        if not self.presentation.error:
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

    def restore_last_reply(self):
        self._last_reply = next(
            (
                message["content"]
                for message in reversed(self.presentation.messages)
                if message["role"] == "assistant"
            ),
            "",
        )

    def _after_session_changed(self, result: SessionStepResult) -> None:
        session = result.session
        self.refresh_session_state(session)
        self._refresh_review_items()
        self.sessionChanged.emit()
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


    def _set_status(self, value: str) -> None:
        self._status = value
        self.statusChanged.emit()


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


    def configure_local_speech(self, library):
        self._local_speech = library.local_service
        library.configure_preview(lambda: self.selectedOutputDeviceId, lambda: self.voice.active)
        library.inferenceStatus.connect(self._local_speech_status)
        library.configurationChanged.connect(self._local_speech_configuration)

    @Slot()
    def _local_speech_configuration(self):
        self.voice.invalidate_cache()
        self.voice.preflight.invalidate()
        self.uiChanged.emit()

    @Slot(str)
    def _local_speech_status(self, value):
        self._speech_status = value
        self.uiChanged.emit()

    def speech_available(self, task):
        return bool(
            (self._local_speech and self._local_speech.enabled(task)) or getattr(self, "_" + task)
        )


    def speech_language(self):
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
            language = self.speech_language()
            method = (
                self._local_speech.transcribe if task == "stt" else self._local_speech.synthesize
            )
            return lambda: method(content, language)
        provider = getattr(self, "_" + task)
        method = provider.transcribe if task == "stt" else provider.synthesize
        return lambda: method(content)


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

        self.run_operation(
            QCoreApplication.translate("Desktop", "正在建立本地引用…"),
            operation,
            self._after_material_loaded,
        )


    @Slot()
    def resumeMaterialPreparation(self):
        if not self._busy:

            async def operation():
                return self._workbench.resume_material_preparation()

            self.run_operation(
                QCoreApplication.translate("Desktop", "正在继续基础理解…"),
                operation,
                self._after_material_loaded,
            )


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
        profile = self.selected_profile()
        self.run_operation(
            QCoreApplication.translate("Desktop", "正在重新分析..."),
            lambda: self._workbench.analyze_current_material(profile=profile),
            self._after_material_loaded,
        )

    def selected_profile(self):
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
                self.run_operation(*self._retry_operation)

    @Slot()
    def dismissError(self):
        self.present_conversation(ConversationEvent("error"))
        self.uiChanged.emit()

    def after_started(self, result):
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
        if self.preferences.autoReadReplies and self.speech_available("tts"):
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
        self.present_conversation(ConversationEvent("invalidate"))
        self.voice.reset()
        if self._audio:
            self._audio.clear()
        self._last_reply = ""
        self._retry_operation = None
        self.uiChanged.emit()

    def begin_shutdown(self):
        if not self._closed:
            self.present_conversation(ConversationEvent("invalidate"))
            self._closed = True
            self.voice.close()
            self._preparation_timer.stop()

        self._worker.begin_shutdown(self.cleanup_resources)

    async def cleanup_resources(self):
        try:
            await self.voice.call.aclose()
        finally:
            try:
                if self._local_speech:
                    await self._local_speech.close()
            finally:
                await self._workbench.aclose()

    def finish_shutdown(self) -> bool:
        if self._worker.finish_shutdown():
            self._clear_audio()
            return True
        return False

    @Slot()
    def close(self):
        self.begin_shutdown()
        self._worker.close(lambda: self._workbench.aclose())
        self.finish_shutdown()


def _local_path(value: str) -> Path | None:
    if not value.strip():
        return None
    url = QUrl(value)
    if url.isValid() and url.isLocalFile():
        return Path(url.toLocalFile())
    return Path(value).expanduser()
