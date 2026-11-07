"""Editable AI connection settings. Saving never changes an in-flight provider."""

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QCoreApplication, Signal, Slot, Qt

from lingualoop.infrastructure.ai_configuration import AIConnection, AIConfigurationStore
from lingualoop.providers.service_probe import probe_models


def error_text(code: str) -> str:
    messages = {
        "ai_api_invalid_url": QCoreApplication.translate("Desktop", "请输入有效的 HTTP 或 HTTPS API 基础地址，不包含账号、查询参数或片段。"),
        "ai_api_missing_key": QCoreApplication.translate("Desktop", "请填写 API Key；留空只能保留已有的有效密钥。"),
        "ai_api_missing_model": QCoreApplication.translate("Desktop", "请读取模型列表并选择推理模型；对话可选择与推理使用同一个模型。"),
        "ai_api_selection_required": QCoreApplication.translate("Desktop", "请从当前服务返回的列表中选择模型后保存。"),
        "ai_api_auth_failed": QCoreApplication.translate("Desktop", "服务拒绝了此 API Key，请检查密钥和访问权限。"),
        "ai_api_models_unsupported": QCoreApplication.translate("Desktop", "此服务不支持读取模型列表，请核对 API 基础地址或联系服务提供方。"),
        "ai_api_rate_limited": QCoreApplication.translate("Desktop", "服务暂时限流，请稍后重新检查。"),
        "ai_api_models_invalid": QCoreApplication.translate("Desktop", "服务未返回有效的模型列表，请核对基础地址后重试。"),
        "ai_api_models_empty": QCoreApplication.translate("Desktop", "此 API Key 下没有可选模型，请检查服务权限后重新读取。"),
        "ai_api_config_unreadable": QCoreApplication.translate("Desktop", "已保存配置无法读取，请重新填写连接信息和密钥后保存。"),
        "ai_api_secret_storage_unavailable": QCoreApplication.translate("Desktop", "此平台尚未提供安全的密钥保存，请继续使用环境配置。"),
    }
    return messages.get(code, QCoreApplication.translate(
        "Desktop", "操作未完成，请检查服务连接或本地配置文件的写入权限。"
    ))


class AIServiceSettingsController(QObject):
    changed = Signal()
    secretCleared = Signal()

    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self.vm, self.worker = vm, vm.worker
        database = getattr(vm.workbench._event_store, "path", None)
        if database is None:
            from lingualoop.infrastructure.sqlite_store import default_database_path
            database = default_database_path()
        self.store = AIConfigurationStore(Path(database).parent / "ai-services.json")
        self._base = self._reasoning = self._dialogue = ""
        self._key = self._existing_key = ""
        self._status = self._error = ""
        self._models = []
        self._models_loaded = False
        self._job = ""
        self._revision = 0
        self._closed = self._restart = False
        self.probe = probe_models
        self._saved = self.store.path.is_file()
        active = getattr(vm.workbench.provider, "_settings", None)
        self._environment = None
        if "Mock" not in vm.providerLabel:
            from lingualoop.providers.openai_compatible import OpenAICompatibleLLMSettings
            try:
                self._environment = OpenAICompatibleLLMSettings.from_env()
            except (ValueError, RuntimeError):
                pass
        if active:
            self._base, self._reasoning = active.base_url, active.reasoning_model
            self._dialogue = active.dialogue_model or active.reasoning_model
            self._existing_key = active.api_key.get_secret_value()
        try:
            saved = self.store.load()
            if saved:
                self._base, self._reasoning, self._dialogue = (
                    saved.base_url, saved.reasoning_model, saved.dialogue_model
                )
                self._existing_key = saved.api_key
        except ValueError:
            self._existing_key = ""
            self._error = error_text("ai_api_config_unreadable")
        self.worker.jobCompleted.connect(self._completed, Qt.ConnectionType.QueuedConnection)

    def _edit(self, attribute: str, value: str) -> None:
        if value == getattr(self, attribute):
            return
        setattr(self, attribute, value)
        if attribute in {"_base", "_key"}:
            self._models = []
            self._models_loaded = False
        self._revision += 1
        self._error = self._status = ""
        self.changed.emit()

    @Property(str, notify=changed)
    def baseUrl(self):
        return self._base

    @baseUrl.setter
    def baseUrl(self, value):
        self._edit("_base", value)

    @Property(str, notify=changed)
    def reasoningModel(self):
        return self._reasoning

    @reasoningModel.setter
    def reasoningModel(self, value):
        self._edit("_reasoning", value)

    @Property(str, notify=changed)
    def dialogueModel(self):
        return self._dialogue

    @dialogueModel.setter
    def dialogueModel(self, value):
        self._edit("_dialogue", value)

    @Slot(str)
    def setApiKey(self, value: str) -> None:
        self._edit("_key", value)

    @Property(bool, notify=changed)
    def hasApiKey(self):
        return bool(self._existing_key)

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._job)

    @Property(list, notify=changed)
    def modelOptions(self):
        return self._models

    @Property(bool, notify=changed)
    def modelsLoaded(self) -> bool:
        return self._models_loaded

    @Property(bool, notify=changed)
    def canSave(self) -> bool:
        return (
            not self.busy and self._models_loaded and self._reasoning in self._models
            and (not self._dialogue or self._dialogue in self._models)
        )

    @Property(str, notify=changed)
    def modelSelectionHint(self) -> str:
        if not self._models_loaded:
            return QCoreApplication.translate("Desktop", "先填写 API 地址和密钥，再读取模型列表。")
        if self._models and (
            self._reasoning and self._reasoning not in self._models
            or self._dialogue and self._dialogue not in self._models
        ):
            return QCoreApplication.translate("Desktop", "已选模型不在当前服务列表中，请重新选择。")
        return ""

    @Property(str, notify=changed)
    def statusText(self):
        return self._status

    @Property(str, notify=changed)
    def errorText(self):
        return self._error

    @Property(bool, notify=changed)
    def hasSavedConfiguration(self):
        return self._saved

    @Property(bool, notify=changed)
    def restartRequired(self):
        return self._restart

    @Property(str, notify=changed)
    def sourceText(self):
        if self._saved:
            return QCoreApplication.translate("Desktop", "界面保存的配置优先")
        if self._environment:
            return QCoreApplication.translate("Desktop", "当前使用本地环境配置")
        return QCoreApplication.translate("Desktop", "尚未配置 AI 服务")

    def _connection(self, *, require_models=True) -> AIConnection:
        return AIConnection.validated(
            self._base, self._reasoning if require_models else self._reasoning or "metadata-check",
            self._dialogue, self._key or self._existing_key,
        )

    @Slot()
    def save(self) -> None:
        try:
            if not self.canSave:
                raise ValueError("ai_api_selection_required")
            connection = self._connection()
            self.store.save(connection)
        except (ValueError, OSError) as error:
            self._error = error_text(str(error))
        else:
            self._base, self._reasoning, self._dialogue = (
                connection.base_url, connection.reasoning_model, connection.dialogue_model
            )
            self._existing_key, self._key = connection.api_key, ""
            self._saved = self._restart = True
            self._error = ""
            self._status = QCoreApplication.translate("Desktop", "配置已保存，重新打开软件后生效。")
            self.secretCleared.emit()
        self.changed.emit()

    @Slot()
    def useEnvironment(self) -> None:
        try:
            self.store.clear()
        except OSError:
            self._error = error_text("ai_api_write_failed")
        else:
            self._saved, self._restart = False, True
            self._revision += 1
            self._models, self._models_loaded = [], False
            self._existing_key = self._key = ""
            if self._environment:
                self._existing_key = self._environment.api_key.get_secret_value()
                self._base = self._environment.base_url
                self._reasoning = self._environment.reasoning_model
                self._dialogue = self._environment.dialogue_model or self._reasoning
            else:
                self._base = self._reasoning = self._dialogue = ""
            self._error = ""
            self._status = QCoreApplication.translate("Desktop", "已移除界面保存的配置，重启后读取本地环境。")
            self.secretCleared.emit()
        self.changed.emit()

    @Slot()
    def testConnection(self) -> None:
        if self._closed or self._job:
            return
        try:
            connection = self._connection(require_models=False)
        except ValueError as error:
            self._error = error_text(str(error))
            self.changed.emit()
            return
        self._job = "ai-api-probe-" + uuid4().hex
        self._models, self._models_loaded = [], False
        self._probe_revision = self._revision
        self._status = QCoreApplication.translate("Desktop", "正在检查连接并读取模型列表…")
        self._error = ""
        self.worker.submit_job(self._job, lambda: self.probe(connection))
        self.changed.emit()

    @Slot(str, object, str)
    def _completed(self, job, result, error) -> None:
        if not job.startswith("ai-api-probe-"):
            return
        self.worker.forget_job(job)
        if self._closed or job != self._job:
            return
        self._job = ""
        if self._probe_revision != self._revision:
            self._status = QCoreApplication.translate("Desktop", "连接信息已修改，请重新检查。")
        elif error:
            self._status, self._error = "", error_text(error)
        else:
            self._models = result
            self._models_loaded = True
            self._error = "" if result else error_text("ai_api_models_empty")
            self._status = QCoreApplication.translate(
                "Desktop", "服务连接成功，读取到 %1 个模型；这不代表已验证模型生成能力。"
            ).replace("%1", str(len(result)))
        self.changed.emit()

    def close(self) -> None:
        self._closed = True
        self.worker.cancel_job(self._job)
        self._key = self._existing_key = ""
