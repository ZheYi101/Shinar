"""Single Qt adapter over independently owned library operation and catalog state."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, QUrl, Slot, Signal, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaDevices

from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.downloads import ModelStore
from shinar.local_speech.storage import default_cache_root
from shinar.local_speech.compute import (
    load_compute,
)
from shinar.local_speech.service import LocalSpeechService
from shinar.local_speech.model_profile import (
    voice_choice,
    voices,
)
from shinar.desktop.speech_library.jobs import SpeechPreparationJobs


from shinar.desktop.presentation.conversation_presentation import display_value
from shinar.desktop.speech_library.state import LibraryRequest, LibraryOperations, CatalogProjection
from shinar.desktop.speech_library.monitor import ResourceMonitor
from shinar.desktop.speech_library.work import LibraryWork
from shinar.local_speech.storage import atomic_json, read_json
from shinar.local_speech.storage_lease import storage_lease
from shinar.local_speech.compute import save_compute, runtime_version
from shinar.local_speech import adapter_revision
from shinar.desktop.speech_library.formats import catalog_display, work_error


class SpeechLibraryViewModel(QObject):
    changed = Signal()
    statusChanged = Signal()
    runtimesChanged = Signal()
    modelsChanged = Signal()
    progressChanged = Signal()
    downloadsChanged = Signal()
    configurationChanged = Signal()
    inferenceStatus = Signal(str)
    resourcesChanged = Signal()
    _event = Signal(object)

    def __init__(
        self,
        root=None,
        parent=None,
        *,
        catalog=None,
        store_factory=ModelStore,
        work_factory=LibraryWork,
    ):
        super().__init__(parent)
        self._store_factory, self._work_factory = store_factory, work_factory
        self.store = store_factory(Path(root) if root else default_cache_root())
        self._operations, self._projection, self._monitor = (
            LibraryOperations(),
            CatalogProjection(),
            ResourceMonitor(),
        )
        self._projection.configure(catalog if catalog is not None else load_catalog())
        self.changed.connect(self.statusChanged)
        self._event.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        self.local_service = LocalSpeechService(self.store.root, status=self.inferenceStatus.emit)
        self.inferenceStatus.connect(self._inference_status)
        self._resource_timer, self._timer = QTimer(self), QTimer(self)
        self._resource_timer.setInterval(2000)
        self._resource_timer.timeout.connect(self._poll_resources)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.progressChanged)
        self._audio, self._player = QAudioOutput(self), QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.errorOccurred.connect(lambda *_: self._playback_error())
        self._preview_device, self._voice_active = None, lambda: False
        self._downloads = SpeechPreparationJobs(self)
        self._downloads.activityChanged.connect(self._download_activity)
        self._downloads.finished.connect(self._download_finished)

    @property
    def catalog(self):
        from shinar.local_speech.catalog import ModelPackage

        return tuple(ModelPackage.model_validate_json(value) for value in self._projection.packages)

    def configure_catalog(self, packages):
        if not self.busy and not self._operations.snapshot.closed:
            self._projection.configure(packages)

    @property
    def operation_snapshot(self):
        return self._operations.snapshot

    @property
    def catalog_snapshot(self):
        return self._projection.snapshot

    def _request_snapshot(self):
        return LibraryRequest(
            self.store.root,
            self._projection.packages,
            self.language,
            self.scenario,
            load_compute(self.store.root).model_dump_json(),
        )

    def _package(self, identity):
        return next(package for package in self.catalog if package.id == identity)

    def _launch(self, kind, args, title, kwargs=None):
        if self._operations.snapshot.closed or self.operationBusy:
            return
        request, factory, backend = (
            self._request_snapshot(),
            self._work_factory,
            self._store_factory,
        )
        parameters = dict(kwargs or {})

        def operation(cancel, emit):
            return factory(request, backend, cancel, emit).execute(kind, args, parameters)

        if self._operations.start(title, operation, self._event.emit):
            self._player.stop()
            self._timer.start()
            self.progressChanged.emit()
            self.changed.emit()

    @Slot(object)
    def _receive(self, event):
        if event.kind == "resources":
            if self._monitor.accept(event):
                self.resourcesChanged.emit()
            return
        if not self._operations.accept(event):
            return
        if event.kind == "stage":
            self._setup_status(event.value)
        elif event.kind == "completed":
            self._finish_result(event.value, event.error)

    def _download_activity(self):
        self._projection.download_changed()
        self.downloadsChanged.emit()
        self.changed.emit()

    def _download_finished(self, identity):
        if self._operations.snapshot.closed:
            return
        if self.operationBusy:
            self._projection.defer_refresh()
        else:
            self.refresh()

    def _poll_resources(self):
        self._monitor.poll(self.local_service.pids, self.local_service.gpu_pids, self._event.emit)

    @Slot()
    def refresh(self):
        self._launch("_snapshot", (), QCoreApplication.translate("Desktop", "检测硬件与本地模型…"))

    @Slot(str, str)
    def setFilter(self, language, scenario):
        if (
            self.operationBusy
            or self._operations.snapshot.closed
            or language not in {"zh", "en", "ja", "ko", "yue", "de", "fr", "es"}
            or scenario not in {"conversation", "import", "reading"}
        ):
            return
        self._projection.filter(language, scenario)
        self.refresh()

    @Slot()
    def cancel(self):
        self._operations.cancel()

    @Slot()
    def begin_shutdown(self):
        self._operations.close()
        self._monitor.close()
        self._downloads.begin_shutdown()
        self._timer.stop()
        self._resource_timer.stop()
        self._player.stop()

    def finish_shutdown(self):
        return (
            self._operations.finished()
            and self._monitor.finished()
            and self._downloads.finish_shutdown()
        )

    def close(self):
        from time import monotonic, sleep

        self.begin_shutdown()
        self._downloads.close()
        deadline = monotonic() + 15
        while not self.finish_shutdown():
            if monotonic() >= deadline:
                raise RuntimeError("speech_library_shutdown_incomplete")
            sleep(0.01)

    @Property(QObject, constant=True)
    def downloadJobs(self):
        return self._downloads

    @Property(int, notify=downloadsChanged)
    def downloadCount(self):
        return self._downloads.active_count

    @Property(int, notify=downloadsChanged)
    def downloadRevision(self):
        return self._projection.revision

    @Property(bool, notify=changed)
    def operationBusy(self):
        return self._operations.snapshot.busy

    @Slot(str, result=bool)
    def hasDownload(self, model_id):
        return self._downloads.contains_active(model_id)

    def configure_preview(
        self, device_id: Callable[[], str], voice_active: Callable[[], bool]
    ) -> None:
        """GUI-only device getters; never change devices or add preview echo during a call."""
        self._preview_device, self._voice_active = (device_id, voice_active)

    @Property("QVariantMap", notify=changed)
    def compute(self):
        return load_compute(self.store.root).model_dump()

    @Property("QVariantMap", notify=changed)
    def lastSetupError(self):
        if display_value(self._operations.snapshot.error):
            return display_value(self._operations.snapshot.error)
        failed = next((r for r in reversed(self._downloads.rows()) if r["state"] == "failed"), None)
        return {"code": failed["errorCode"], "modelId": failed["modelId"]} if failed else {}

    @Property("QVariantMap", notify=runtimesChanged)
    def runtimes(self):
        return display_value(self._projection.snapshot["runtimes"])

    @Property("QVariantMap", notify=modelsChanged)
    def storageUsage(self):
        return display_value(self._projection.snapshot["storageUsage"])

    @Slot(str)
    def _setup_status(self, stage):
        if self._operations.snapshot.closed:
            return
        messages = {
            "speech_setup_bootstrap": QCoreApplication.translate(
                "Desktop", "正在准备独立 Python 与安装工具…"
            ),
            "speech_setup_resources": QCoreApplication.translate(
                "Desktop", "正在准备模型所需词典与共享资源…"
            ),
            "speech_setup_wheels": QCoreApplication.translate(
                "Desktop", "正在下载并校验固定运行库…"
            ),
            "speech_setup_installing": QCoreApplication.translate("Desktop", "正在离线安装运行库…"),
            "speech_setup_probing": QCoreApplication.translate("Desktop", "正在执行实际计算验证…"),
            "speech_setup_model": QCoreApplication.translate("Desktop", "正在下载并校验模型权重…"),
        }
        self._operations.status(messages.get(stage, self._operations.snapshot.status))
        self.changed.emit()

    @Property(str, notify=resourcesChanged)
    def resourceSummary(self):
        value = self._monitor.snapshot
        lines = [
            QCoreApplication.translate(
                "Desktop",
                "GPU {value0} · {value1} · 整卡显存 {value2} / {value3} MiB · 整卡使用率 {value4:.0f}%",
            ).format(
                value0=g["index"],
                value1=g["name"],
                value2=g["used_mb"],
                value3=g["total_mb"],
                value4=g["utilization"],
            )
            for g in value.get("gpus", [])
        ]
        used = value.get("speech_process_mb")
        if value:
            lines.append(
                QCoreApplication.translate("Desktop", "本软件语音进程 {value0} 个 · 显存 ").format(
                    value0=value["process_count"]
                )
                + (
                    f"{used} MiB"
                    if used is not None
                    else QCoreApplication.translate("Desktop", "驱动未提供进程级读数")
                )
            )
        return "\n".join(lines) or QCoreApplication.translate(
            "Desktop", "正在读取资源；当前仅支持 NVIDIA CUDA GPU。"
        )

    @Slot(str)
    def _inference_status(self, value):
        if self._operations.snapshot.closed:
            return
        self._operations.status(value)
        self.statusChanged.emit()

    @Slot(bool)
    def setResourceMonitoring(self, enabled):
        if self._operations.snapshot.closed:
            return
        self._monitor.enable(enabled)
        if enabled:
            self._resource_timer.start()
            self._poll_resources()
        else:
            self._resource_timer.stop()

    @Property("QVariantList", notify=modelsChanged)
    def models(self):
        return display_value(self._projection.snapshot["rows"])

    @Property(bool, notify=changed)
    def busy(self):
        return self._operations.snapshot.busy or bool(self._downloads.active_count)

    @Property(str, notify=statusChanged)
    def status(self):
        return self._operations.snapshot.status

    @Property(str, notify=changed)
    def language(self):
        return self._projection.language

    @Property(str, notify=changed)
    def scenario(self):
        return self._projection.scenario

    @Property(str, notify=changed)
    def operation(self):
        return self._operations.snapshot.operation

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._operations.snapshot.progress

    @Property(str, notify=changed)
    def cachePath(self):
        return str(self.store.root)

    @Property(str, notify=changed)
    def hardwareSummary(self):
        h = self._projection.snapshot["hardware"]
        if not h:
            return QCoreApplication.translate("Desktop", "尚未检测硬件")
        free = h.get("available_ram_bytes")
        ram = (
            QCoreApplication.translate("Desktop", "{value0:.1f} GiB 可用内存").format(
                value0=free / 1024**3
            )
            if free
            else QCoreApplication.translate("Desktop", "可用内存未知")
        )
        gpu = "；".join(
            (
                g["name"]
                + QCoreApplication.translate("Desktop", "（可用 {value0} MiB）").format(
                    value0=g["available_mb"]
                )
                for g in h["gpus"]
            )
        )
        return QCoreApplication.translate(
            "Desktop", "{value0} · {value1} 逻辑核心 · {value2} · 磁盘剩余 {value3:.1f} GiB"
        ).format(
            value0=h.get("cpu_name", h["cpu"]),
            value1=h["logical_cpus"],
            value2=ram,
            value3=h["disk_free_bytes"] / 1024**3,
        ) + ("\n" + gpu if gpu else "")

    @Slot(str)
    def preview(self, id):
        if self._operations.snapshot.closed:
            return
        if self._voice_active():
            self._operations.status(
                QCoreApplication.translate("Desktop", "请先停止语音，再试听模型声音。")
            )
            self.changed.emit()
            return
        row = next(
            (r for r in display_value(self._projection.snapshot["rows"]) if r["id"] == id), {}
        )
        path = Path(row.get("preview") or "")
        if path.is_file() and path.resolve().is_relative_to(
            (self.store.root / "reports").resolve()
        ):
            if self._preview_device:
                selected = self._preview_device()
                device = next(
                    (d for d in QMediaDevices.audioOutputs() if bytes(d.id()).hex() == selected),
                    None,
                )
                if device is None:
                    self._operations.status(
                        QCoreApplication.translate(
                            "Desktop", "所选播放设备不可用，请在音频设置中重新选择。"
                        )
                    )
                    self.changed.emit()
                    return
                self._audio.setDevice(device)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.play()
            credit = voice_choice(self.store.root, id).get("attribution", "")
            if credit:
                self._operations.status(credit)
                self.changed.emit()

    def _playback_error(self):
        if self._operations.snapshot.closed:
            return
        self._operations.status(
            QCoreApplication.translate(
                "Desktop", "试听播放失败，可重新测速生成音频并检查输出设备。"
            )
        )
        self.changed.emit()

    @Slot()
    def stopPreview(self):
        self._player.stop()

    @Slot(str)
    def prepareRuntime(self, device):
        if device not in {"cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu"}:
            return
        if self.local_service.pids:
            self._operations.status(
                QCoreApplication.translate(
                    "Desktop", "请先停止语音并释放已加载模型，再修复运行环境。"
                )
            )
            self.changed.emit()
            return
        self._launch(
            "prepareRuntime",
            (device,),
            QCoreApplication.translate(
                "Desktop", "准备独立运行环境与必要运行库（GPU 下载可能较大）…"
            ),
            {},
        )

    @Slot(str)
    def checkRuntime(self, device):
        if device not in {"cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu"}:
            return
        self._launch(
            "checkRuntime",
            (device,),
            QCoreApplication.translate("Desktop", "检查运行环境并执行真实计算探针…"),
            {},
        )

    @Slot(str)
    def uninstall(self, id):
        self._launch("uninstall", (id,), QCoreApplication.translate("Desktop", "卸载模型…"), {})

    @Slot(str)
    def verify(self, id):
        self._launch("verify", (id,), QCoreApplication.translate("Desktop", "校验本地文件…"), {})

    @Slot(str, str)
    def runBenchmark(self, id, wav):
        self._launch(
            "_run_benchmark",
            (id, QUrl(wav).toLocalFile() if wav else ""),
            QCoreApplication.translate("Desktop", "使用内置示例测速（含预热与 5 次热态）…")
            if not wav
            else QCoreApplication.translate("Desktop", "使用所选录音测速（含预热与 5 次热态）…"),
            {},
        )

    @Slot(str)
    def benchmarkAndSelect(self, id):
        self._launch(
            "_run_benchmark",
            (id, ""),
            QCoreApplication.translate("Desktop", "使用内置示例测速（含预热与 5 次热态）…"),
            {"select_after": True},
        )

    @Slot(str)
    def runPairBenchmark(self, wav):
        self._launch(
            "runPairBenchmark",
            (QUrl(wav).toLocalFile() if wav else "",),
            QCoreApplication.translate("Desktop", "STT + TTS 同时运行测速…"),
            {},
        )

    def _finish_result(self, result, error):
        self._timer.stop()
        if result:
            self._projection.apply(catalog_display(result))
            self.runtimesChanged.emit()
            self.modelsChanged.emit()
        error = work_error(error)
        errors = {
            "speech_runtime_nltk_missing": QCoreApplication.translate(
                "Desktop", "本地英语发音资料缺失，请重新准备 Melo 运行环境。"
            ),
            "speech_storage_busy": QCoreApplication.translate(
                "Desktop", "语音存储正在维护，请等待操作结束后重试。"
            ),
            "speech_storage_moved": QCoreApplication.translate(
                "Desktop", "语音存储位置已更改，请退出并重新打开软件。"
            ),
            "speech_voice_terms_required": QCoreApplication.translate(
                "Desktop", "请先阅读并确认此版本的语音模型与角色条款。"
            ),
            "speech_runtime_not_ready": QCoreApplication.translate(
                "Desktop", "请先准备此模型所需的运行环境。"
            ),
            "speech_device_unsupported": QCoreApplication.translate(
                "Desktop", "此声音尚未开放 GPU，请选择自动或 CPU。"
            ),
            "speech_runtime_platform_unsupported": QCoreApplication.translate(
                "Desktop", "此运行环境当前仅支持 Windows x64 非冻结桌面版。"
            ),
            "speech_runtime_probe_failed": QCoreApplication.translate(
                "Desktop", "运行环境未通过实际计算验证，请检查驱动或重新准备。"
            ),
            "speech_setup_disk_insufficient": QCoreApplication.translate(
                "Desktop", "缓存盘空间不足，请查看容量说明中的安装空间预算，释放空间后重试。"
            ),
            "speech_voice_invalid": QCoreApplication.translate(
                "Desktop", "声音选项无效，请重新选择。"
            ),
            "speech_setup_cancelled": QCoreApplication.translate(
                "Desktop", "准备已取消，已校验下载保留，可继续。"
            ),
            "speech_benchmark_sample_unavailable": QCoreApplication.translate(
                "Desktop", "此语言暂未附带测速示例，请在详情中使用自己的录音测速。"
            ),
            "speech_benchmark_sample_invalid": QCoreApplication.translate(
                "Desktop", "内置测速音频校验失败，请修复软件安装后重试。"
            ),
        }
        error = (
            errors.get(
                error,
                QCoreApplication.translate(
                    "Desktop", "本地语音准备未完成，请检查网络、磁盘和运行环境后重试。"
                ),
            )
            if error.startswith("speech_")
            else error
        )
        self._operations.status(error)
        self.changed.emit()

        if not error and result and result.get("selectAfterBenchmark"):
            model_id, language, scenario = result["selectAfterBenchmark"]
            if (language, scenario) == (self.language, self.scenario):
                self.select(model_id)

        if self._projection.take_refresh():
            self.refresh()

    @Slot(str, "QVariant")
    def setCompute(self, name, value):
        if (
            self._operations.snapshot.closed
            or self.operationBusy
            or name not in type(load_compute(self.store.root)).model_fields
        ):
            return
        try:
            settings = load_compute(self.store.root)
            updated = type(settings).model_validate({**settings.model_dump(), name: value})
        except ValueError:
            self._operations.status(QCoreApplication.translate("Desktop", "计算设置的数值无效。"))
            self.changed.emit()
            return
        if not self._save_settings(lambda: save_compute(self.store.root, updated)):
            return
        self.local_service.request_release()
        self.configurationChanged.emit()
        self.refresh()

    @Slot()
    def releaseModels(self):
        if self._operations.snapshot.closed:
            return
        self.local_service.request_release()
        self._operations.status(
            QCoreApplication.translate("Desktop", "正在释放空闲模型；运行中的推理会先完成。")
        )
        self.changed.emit()

    @Slot(str, bool)
    def acceptVoiceTerms(self, id, accepted):
        if self._operations.snapshot.closed or self.operationBusy:
            return
        package = self._package(id)
        data = read_json(self.store.root / "voice-terms.json", {})
        if accepted:
            data[id] = package.fingerprint
        else:
            data.pop(id, None)
        if not self._save_settings(lambda: atomic_json(self.store.root / "voice-terms.json", data)):
            return
        self.refresh()

    @Slot(str, str)
    def selectVoice(self, id, voice_id):
        if (
            self._operations.snapshot.closed
            or self.operationBusy
            or not any((v["id"] == voice_id for v in voices(id)))
        ):
            return
        data = read_json(self.store.root / "voices.json", {})
        data[id] = voice_id
        if not self._save_settings(lambda: atomic_json(self.store.root / "voices.json", data)):
            return
        self.refresh()

    @Slot(str)
    def select(self, id):
        if self._operations.snapshot.closed or self.operationBusy:
            return
        package = self._package(id)
        row = next((r for r in self.models if r["id"] == id), {})
        if not row.get("measured") or not row.get("installed"):
            return
        if row.get("excluded"):
            self._operations.status(
                QCoreApplication.translate(
                    "Desktop", "此配置已在严格评测与试听中排除，请选择其他模型。"
                )
            )
            self.changed.emit()
            return
        if (
            package.task == "stt"
            and self.scenario == "conversation"
            and (not row.get("withinRealtimeBudget"))
        ):
            self._operations.status(
                QCoreApplication.translate(
                    "Desktop",
                    "此模型在当前设备上平均超过 500 ms，请改用 GPU 测速或选择其他识别模型。",
                )
            )
            self.changed.emit()
            return
        selected = read_json(self.store.root / "selections.json", {})
        selected[f"{self.language}:{self.scenario}:{package.task}"] = {
            "id": id,
            "fingerprint": package.fingerprint,
            "runtime_version": runtime_version(package),
            "adapter_revision": adapter_revision(package.adapter),
            "voice_id": voice_choice(self.store.root, id).get("id"),
            **{
                k: v
                for k, v in voice_choice(self.store.root, id).items()
                if k in {"speaker_id", "style_id"}
            },
        }
        def save_selection():
            atomic_json(self.store.root / "selections.json", selected)
            if self.scenario == "conversation":
                settings = load_compute(self.store.root)
                save_compute(
                    self.store.root, settings.model_copy(update={f"local_{package.task}": True})
                )

        if not self._save_settings(save_selection):
            return
        if self.scenario == "conversation":
            self.local_service.request_release()
            self.configurationChanged.emit()
        self._projection.select(id, package.task)
        self.modelsChanged.emit()
        self._operations.status(
            QCoreApplication.translate(
                "Desktop",
                "已保存本语言的模型；后续语音按计算设置绑定，当前轮次保留原配置，连续语音需重新开始。",
            )
        )
        self.changed.emit()

    def _save_settings(self, write):
        try:
            with storage_lease(self.store.root):
                write()
        except (RuntimeError, OSError):
            self._operations.status(QCoreApplication.translate(
                "Desktop", "存储正在维护或位置已更改。请等待操作结束；迁移成功后请重启软件。"
            ))
            self.changed.emit()
            return False
        return True

    @Slot(str)
    def install(self, id):
        self._enqueue_preparation(id, with_runtime=False)

    @Slot(str)
    def preparePackage(self, id):
        self._enqueue_preparation(id, with_runtime=True)

    def _enqueue_preparation(self, id, *, with_runtime):
        if self._operations.snapshot.closed:
            return
        request, factory, backend = (
            self._request_snapshot(),
            self._work_factory,
            self._store_factory,
        )
        package = self._package(id)

        def operation(cancel, stage, transfer):
            work = factory(request, backend, cancel, lambda *_: None)
            work.preparation_operation(id, with_runtime=with_runtime)(cancel, stage, transfer)

        self._downloads.enqueue(package.id, package.name, package.task, request.language, operation)
