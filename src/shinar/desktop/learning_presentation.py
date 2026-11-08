"""QML projections on the single LearningViewModel instance."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, Property, Signal, Slot, Qt, QCoreApplication

from .conversation_presentation import ConversationEvent, display_value

from shinar.core.reading_scope import scope_material, reading_end, paragraph_boundary


AsyncOperation = Callable[[], Coroutine[Any, Any, Any]]


class LearningPresentation:
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

    @Property(str, constant=True)
    def providerLabel(self) -> str:
        return self._provider_label

    @Property(dict, constant=True)
    def modelServices(self) -> dict[str, str]:
        settings = getattr(self._workbench.provider, "connection_settings", None)
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

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy or self.voice.active

    @Property(bool, notify=busyChanged)
    def operationBusy(self) -> bool:
        return bool(self._busy or self.voice.pending_job or self.voice.call.connectionState in
                    {"preparing", "connecting", "reconnecting", "stopping"})

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
            material = self._workbench.session_material()
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
        return display_value(self.presentation.messages)

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

    def refresh_session_state(self, session: Any | None = None) -> None:
        self.present_conversation(ConversationEvent("refresh", session=session))

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
        return self.presentation.error

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
                dict(topic.model_dump(), category_label=topic_category_label(topic.category))
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
        return self.presentation.streaming_text

    @Property(str, notify=uiChanged)
    def pendingUserText(self):
        return self.presentation.pending_user_text

    @Property(str, notify=uiChanged)
    def responseTiming(self):
        return self.presentation.response_timing

    @Property(str, notify=uiChanged)
    def preparationStatus(self):
        return {
            "idle": "",
            "preparing": QCoreApplication.translate("Desktop", "正在后台准备下一轮参考…"),
            "ready": QCoreApplication.translate("Desktop", "下一轮参考已准备"),
            "unavailable": QCoreApplication.translate("Desktop", "后台准备暂不可用，对话仍可继续"),
        }.get(self._preparation_state, "")

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
            self.speech_available("stt")
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
        return self.presentation.recording_seconds

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
        return bool(self._last_reply and self.speech_available("tts"))

    @Property(str, notify=uiChanged)
    def speechLanguage(self):
        return self.speech_language()

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

    @Property(bool, notify=materialChanged)
    def canResumeMaterialPreparation(self):
        material = self._workbench.material
        knowledge = material.analysis.knowledge if material and material.analysis else None
        return bool(knowledge and knowledge.status in {"saved", "partial", "failed"})

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


def topic_category_label(category: str) -> str:
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
