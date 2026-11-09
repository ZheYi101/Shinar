"""Qt adapter for identified, owned speech-storage maintenance jobs."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QCoreApplication, Signal, Slot, QUrl

from shinar.desktop.tasks.worker import AsyncWorker
from shinar.infrastructure.blocking_jobs import BlockingRequest, run_blocking


def _size(value):
    amount = float(value or 0)
    return f"{amount / 1024**3:.2f} GiB" if amount >= 1024**3 else f"{amount / 1024**2:.1f} MiB"


def _message(code):
    aliases = {
        "speech_storage_plan_changed": "speech_storage_changed",
        "speech_storage_moved": "speech_storage_relocated",
        "speech_setup_cancelled": "speech_storage_cancelled",
        "cancelled": "speech_storage_cancelled",
    }
    messages = {
        "speech_storage_busy": QCoreApplication.translate(
            "SpeechStorageController", "语音资源正在使用中。请结束通话、测速或下载后重试。"),
        "speech_storage_changed": QCoreApplication.translate(
            "SpeechStorageController", "文件已发生变化，请重新扫描后再清理。"),
        "speech_storage_relocated": QCoreApplication.translate(
            "SpeechStorageController", "存储位置已更改，请退出并重新打开软件。"),
        "speech_storage_destination_not_empty": QCoreApplication.translate(
            "SpeechStorageController", "请选择一个新的空文件夹。"),
        "speech_storage_invalid_destination": QCoreApplication.translate(
            "SpeechStorageController", "新位置不能位于原目录内、包含原目录或使用磁盘根目录。"),
        "speech_storage_insufficient_space": QCoreApplication.translate(
            "SpeechStorageController", "目标磁盘可用空间不足。"),
        "speech_storage_verification_failed": QCoreApplication.translate(
            "SpeechStorageController", "文件或运行环境验证未通过，原位置保留。请检查磁盘后重试。"),
        "speech_storage_location_unavailable": QCoreApplication.translate(
            "SpeechStorageController", "选定的存储位置不可用，请连接相应磁盘后重试。"),
        "speech_storage_link_unsupported": QCoreApplication.translate(
            "SpeechStorageController", "所选位置含有链接或目录联接，请选择普通文件夹。"),
        "speech_storage_cancelled": QCoreApplication.translate(
            "SpeechStorageController", "操作已取消。"),
    }
    return messages.get(aliases.get(code, code), QCoreApplication.translate(
        "SpeechStorageController", "存储操作未完成。原位置保留，请检查磁盘权限、可用空间后重试。"))


async def _nothing():
    return None


class SpeechStorageController(QObject):
    """Own only maintenance presentation; model services keep their existing root."""

    changed = Signal()
    _stageArrived = Signal(str, str)

    def __init__(self, root, *, config_path=None, location_locked=False,
                 available=lambda: True, release=lambda: None, runner=run_blocking, parent=None):
        super().__init__(parent)
        self._root = Path(root).absolute()
        self._config_path = config_path
        self._location_locked = location_locked
        self._available = available
        self._release = release
        self._runner = runner
        self._worker = AsyncWorker(self)
        self._worker.jobCompleted.connect(self._completed)
        self._stageArrived.connect(self._stage)
        self._job = ""
        self._operation = ""
        self._cancel = None
        self._inventory = {}
        self._preview = {}
        self._status = ""
        self._restart = False
        self._closing = False

    @Property(str, notify=changed)
    def location(self):
        return str(self._root)

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._job)

    @Property(bool, notify=changed)
    def canChangeLocation(self):
        return not (self._location_locked or self._restart or self._closing or self.busy)

    @Property(bool, notify=changed)
    def restartRequired(self):
        return self._restart

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(str, notify=changed)
    def locationExplanation(self):
        if self._location_locked:
            return QCoreApplication.translate(
                "SpeechStorageController", "存储位置由启动环境变量指定，请修改 SHINAR_SPEECH_DIR 后重启。")
        return ""

    @Property("QVariantMap", notify=changed)
    def inventory(self):
        return deepcopy(self._inventory)

    @Property("QVariantMap", notify=changed)
    def migration(self):
        return deepcopy(self._preview)

    @Property(str, notify=changed)
    def totalSize(self):
        return _size(self._inventory.get("totalBytes", 0))

    @Property(str, notify=changed)
    def cacheSize(self):
        return _size(self._inventory.get("reclaimableBytes", 0))

    @Property("QVariantList", notify=changed)
    def categories(self):
        return [
            {"label": QCoreApplication.translate("SpeechStorageController", "模型与运行环境"),
             "size": _size(self._inventory.get("installedBytes", 0))},
            {"label": QCoreApplication.translate("SpeechStorageController", "安装与下载缓存"),
             "size": _size(self._inventory.get("cacheBytes", 0))},
            {"label": QCoreApplication.translate("SpeechStorageController", "配置、报告及其他"),
             "size": _size(self._inventory.get("otherBytes", 0))},
        ]

    @Slot()
    def refresh(self):
        self._start("scan", (str(self._root),))

    @Slot(str)
    def previewMigration(self, destination):
        if not self.canChangeLocation:
            return
        url = QUrl(destination)
        path = url.toLocalFile() if url.isLocalFile() else destination
        self._preview = {}
        self._start("preview", (str(self._root), path))

    @Slot()
    def migrate(self):
        if not self.canChangeLocation or not self._preview:
            return
        destination = self._preview["destination"]
        self._start("migrate", (str(self._root), destination),
                    {"config_path": self._config_path})

    @Slot()
    def clearMigration(self):
        if not self.busy:
            self._preview = {}
            self.changed.emit()

    @Slot()
    def cleanCaches(self):
        plan_id = self._inventory.get("planId")
        if plan_id and not self._restart and not self._inventory.get("incomplete"):
            self._start("clean", (str(self._root), plan_id))

    @Slot()
    def cancel(self):
        if self._cancel:
            self._cancel.set()
            self._status = QCoreApplication.translate(
                "SpeechStorageController", "正在取消并等待资源释放…")
            self.changed.emit()

    def _start(self, operation, args, options=None):
        if self.busy or self._closing or self._restart:
            return
        if operation in {"clean", "migrate"}:
            if not self._available():
                self._status = _message("speech_storage_busy")
                self.changed.emit()
                return
            self._release()
        identity = uuid4().hex
        stopped = Event()
        request = BlockingRequest("speech_storage_" + operation, args, options)
        self._job, self._operation, self._cancel = identity, operation, stopped
        self._status = (
            QCoreApplication.translate("SpeechStorageController", "正在扫描…")
            if operation == "scan"
            else QCoreApplication.translate("SpeechStorageController", "正在处理…")
        )
        runner = self._runner
        deliver = self._stageArrived.emit

        async def execute():
            return await runner(request, cancel=stopped,
                                on_event=lambda kind, value: deliver(identity, str(value)))

        self._worker.submit_job(identity, execute)
        self.changed.emit()

    @Slot(str, str)
    def _stage(self, identity, stage):
        if identity != self._job or self._closing:
            return
        aliases = {"speech_storage_copying": "copy", "speech_storage_rebuilding_runtime": "runtime"}
        labels = {
            "copy": QCoreApplication.translate("SpeechStorageController", "正在复制模型文件…"),
            "verify": QCoreApplication.translate("SpeechStorageController", "正在校验模型文件…"),
            "runtime": QCoreApplication.translate("SpeechStorageController", "正在重建并验证运行环境…"),
            "commit": QCoreApplication.translate("SpeechStorageController", "正在保存新位置…"),
        }
        self._status = labels.get(aliases.get(stage, stage), QCoreApplication.translate(
            "SpeechStorageController", "正在处理存储文件…"))
        self.changed.emit()

    @Slot(str, object, str)
    def _completed(self, identity, result, error):
        self._worker.forget_job(identity)
        if identity != self._job or self._closing:
            return
        operation = self._operation
        self._job, self._operation, self._cancel = "", "", None
        # A cancellation can race the child's durable location commit. Report
        # the committed location even if its final acknowledgement was lost.
        if operation == "migrate" and error and self._migration_committed():
            error = ""
        if error:
            self._status = _message(error)
        elif operation == "scan":
            self._inventory = dict(result)
            self._status = QCoreApplication.translate(
                "SpeechStorageController", "部分文件无法读取，统计不完整。请检查权限后重新扫描。"
            ) if result.get("incomplete") else ""
        elif operation == "preview":
            self._preview = dict(result)
            self._status = ""
        elif operation == "migrate":
            self._preview = {}
            self._restart = True
            self._status = QCoreApplication.translate(
                "SpeechStorageController", "新位置已验证。请退出并重新打开软件；原位置保留，可确认使用正常后再处理。")
        else:
            self._inventory = {}
            self._status = QCoreApplication.translate("SpeechStorageController", "缓存已清理。")
        self.changed.emit()
        if not error and operation == "clean":
            self.refresh()

    def _migration_committed(self):
        from shinar.configuration_location import load_speech_location

        destination = self._preview.get("destination")
        try:
            saved = load_speech_location(self._config_path)
            return bool(destination and saved and saved.resolve() == Path(destination).resolve())
        except (OSError, RuntimeError, ValueError):
            return False

    def begin_shutdown(self):
        self._closing = True
        self.cancel()
        self._job = ""
        self._worker.begin_shutdown(_nothing)

    def finish_shutdown(self):
        return self._worker.finish_shutdown()

    def close(self):
        self._closing = True
        self.cancel()
        self._job = ""
        self._worker.close(_nothing)
