from __future__ import annotations

import threading
import re
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaDevices

from shinar.local_speech import RUNTIME_VERSION, adapter_revision
from shinar.local_speech.benchmark import benchmark
from shinar.local_speech.catalog import load_catalog
from shinar.local_speech.downloads import DownloadCancelled, ModelStore
from shinar.local_speech.hardware import admission, detect_hardware
from shinar.local_speech.library import model_rows
from shinar.local_speech.storage import atomic_json, default_cache_root, read_json
from shinar.local_speech.compute import (
    load_compute,
    save_compute,
    resolve_device,
    runtime_version,
)
from shinar.local_speech.runtime import (
    install_runtime,
    probe_runtime,
    runtime_python,
    runtime_status,
)
from shinar.local_speech.resources import resource_snapshot
from shinar.local_speech.service import LocalSpeechService
from shinar.local_speech.installation import (
    make_plan,
    managed_status,
    prepare_managed_runtime,
    probe_managed_runtime,
    runtime_id_for,
    runtime_plan,
)
from shinar.local_speech.model_profile import (
    accepted_terms,
    build_profile,
    voice_choice,
    voices,
)
from shinar.local_speech.samples import benchmark_audio
from .speech_jobs import SpeechPreparationJobs
from shinar.local_speech.usage import cached_model_bytes, storage_usage


from shinar.desktop.speech_library_operations import SpeechLibraryOperations

class SpeechLibraryViewModel(QObject, SpeechLibraryOperations):


    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.store = ModelStore(Path(root) if root else default_cache_root())
        self.catalog = load_catalog()
        self._language, self._scenario = "ja", "conversation"
        self._rows, self._hardware = [], {}
        self._storage_usage = {}
        self._runtimes = {
            name: {"prepared": False, "downloadMiB": 0.0, "diskMiB": 0.0}
            for name in ("cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu")
        }
        self.changed.connect(self.statusChanged)
        self._busy, self._status, self._operation = (
            False,
            QCoreApplication.translate("Desktop", "点击刷新，检测当前可用资源。"),
            "",
        )
        self._thread, self._cancel = None, threading.Event()
        self._closing = False
        self._last_setup_error = {}
        self._progress, self._progress_lock = 0.0, threading.Lock()
        self._completed.connect(self._finish)
        self.local_service = LocalSpeechService(self.store.root, status=self.inferenceStatus.emit)
        self.inferenceStatus.connect(self._inference_status)
        self._resources = {}
        self._resource_thread = None
        self._resourcesReady.connect(self._set_resources)
        self._setupStage.connect(self._setup_status)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(2000)
        self._resource_timer.timeout.connect(self._poll_resources)
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.progressChanged)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.errorOccurred.connect(lambda *_: self._playback_error())
        self._preview_device = None
        self._voice_active = lambda: False
        self._downloads = SpeechPreparationJobs(self)
        self._downloads.activityChanged.connect(self._download_activity)
        self._downloads.finished.connect(self._download_finished)
        self._download_revision = 0
        self._refresh_pending = False

    @Property(QObject, constant=True)
    def downloadJobs(self):
        return self._downloads

    @Property(int, notify=SpeechLibraryOperations.downloadsChanged)
    def downloadCount(self):
        return self._downloads.active_count

    @Property(int, notify=SpeechLibraryOperations.downloadsChanged)
    def downloadRevision(self):
        return self._download_revision

    @Property(bool, notify=SpeechLibraryOperations.changed)
    def operationBusy(self):
        return self._busy

    @Slot(str, result=bool)
    def hasDownload(self, model_id):
        return self._downloads.contains_active(model_id)

    @Slot()
    def _download_activity(self):
        self._download_revision += 1
        self.downloadsChanged.emit()
        self.changed.emit()

    @Slot(str)
    def _download_finished(self, job_id):
        if self._closing:
            return
        if self._busy:
            self._refresh_pending = True
        else:
            self.refresh()

    def configure_preview(
        self, device_id: Callable[[], str], voice_active: Callable[[], bool]
    ) -> None:
        """GUI-only device getters; never change devices or add preview echo during a call."""
        self._preview_device, self._voice_active = device_id, voice_active

    @Property("QVariantMap", notify=SpeechLibraryOperations.changed)
    def compute(self):
        return load_compute(self.store.root).model_dump()

    @Property("QVariantMap", notify=SpeechLibraryOperations.changed)
    def lastSetupError(self):
        if self._last_setup_error:
            return self._last_setup_error
        failed = next((r for r in reversed(self._downloads.rows()) if r["state"] == "failed"), None)
        return {"code": failed["errorCode"], "modelId": failed["modelId"]} if failed else {}

    @Property("QVariantMap", notify=SpeechLibraryOperations.runtimesChanged)
    def runtimes(self):
        # QML reads this once for each binding/delegate, including hidden pages.
        # File verification and installation planning belong to the library worker.
        return self._runtimes

    @Property("QVariantMap", notify=SpeechLibraryOperations.modelsChanged)
    def storageUsage(self):
        return self._storage_usage

    def _runtime_snapshot(self):
        values = {
            **{device: runtime_status(self.store.root, device) for device in ("cpu", "cuda")},
            **{
                name: managed_status(self.store.root, name)
                for name in ("voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu")
            },
        }
        index = load_compute(self.store.root).gpu_index
        for name, value in values.items():
            if "cuda" in name and value.get("gpu_index", index) != index:
                value["prepared"] = False
            plan = runtime_plan(self.store.root, "ort-" + name if name in {"cpu", "cuda"} else name)
            value.update(
                downloadMiB=round(plan.download_bytes / 1024**2, 1),
                diskMiB=round(plan.disk_bytes / 1024**2, 1),
            )
        return values

    @Slot(str)
    def _setup_status(self, stage):
        if self._closing:
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
        self._status = messages.get(stage, self._status)
        self.changed.emit()

    def _download_progress(self, done, total):
        with self._progress_lock:
            self._progress = done / total if total else 0

    @Property(str, notify=SpeechLibraryOperations.resourcesChanged)
    def resourceSummary(self):
        value = self._resources
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

    @Slot(object)
    def _set_resources(self, value):
        if self._closing:
            return
        self._resources = value
        self.resourcesChanged.emit()

    @Slot(str)
    def _inference_status(self, value):
        self._status = value
        self.statusChanged.emit()

    def _poll_resources(self):
        if self._closing or (self._resource_thread and self._resource_thread.is_alive()):
            return

        def poll():
            value = resource_snapshot(self.local_service.pids, self.local_service.gpu_pids)
            if not self._closing:
                self._resourcesReady.emit(value)

        self._resource_thread = threading.Thread(target=poll, daemon=True)
        self._resource_thread.start()

    @Slot(bool)
    def setResourceMonitoring(self, enabled):
        if enabled:
            self._resource_timer.start()
            self._poll_resources()
        else:
            self._resource_timer.stop()


    @Property("QVariantList", notify=SpeechLibraryOperations.modelsChanged)
    def models(self):
        return self._rows

    @Property(bool, notify=SpeechLibraryOperations.changed)
    def busy(self):
        return self._busy or bool(self._downloads.active_count)

    @Property(str, notify=SpeechLibraryOperations.statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=SpeechLibraryOperations.changed)
    def language(self):
        return self._language

    @Property(str, notify=SpeechLibraryOperations.changed)
    def scenario(self):
        return self._scenario

    @Property(str, notify=SpeechLibraryOperations.changed)
    def operation(self):
        return self._operation

    @Property(float, notify=SpeechLibraryOperations.progressChanged)
    def progress(self):
        return self._progress

    @Property(str, notify=SpeechLibraryOperations.changed)
    def cachePath(self):
        return str(self.store.root)

    @Property(str, notify=SpeechLibraryOperations.changed)
    def hardwareSummary(self):
        h = self._hardware
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
            g["name"]
            + QCoreApplication.translate("Desktop", "（可用 {value0} MiB）").format(
                value0=g["available_mb"]
            )
            for g in h["gpus"]
        )
        return QCoreApplication.translate(
            "Desktop", "{value0} · {value1} 逻辑核心 · {value2} · 磁盘剩余 {value3:.1f} GiB"
        ).format(
            value0=h.get("cpu_name", h["cpu"]),
            value1=h["logical_cpus"],
            value2=ram,
            value3=h["disk_free_bytes"] / 1024**3,
        ) + ("\n" + gpu if gpu else "")

    def _start(self, title, operation):
        if self._busy or self._closing:
            return
        self._busy, self._operation, self._status = True, title, title
        self._progress = 0
        self._last_setup_error = {}
        self._cancel = threading.Event()
        self._player.stop()

        def run():
            try:
                result = operation()
                error = ""
            except DownloadCancelled as exc:
                result, error = None, str(exc)
            except Exception as exc:
                self._last_setup_error = {
                    "type": type(exc).__name__,
                    "code": str(exc)
                    if re.fullmatch(r"speech_[a-z_]+", str(exc))
                    else "speech_setup_failed",
                }
                result, error = (
                    None,
                    (
                        str(exc)
                        if isinstance(exc, (ValueError, RuntimeError))
                        else QCoreApplication.translate(
                            "Desktop", "操作未完成，请检查网络、磁盘与本地运行依赖后重试。"
                        )
                    ),
                )
                import httpx

                if isinstance(exc, httpx.TransportError):
                    error = QCoreApplication.translate(
                        "Desktop", "下载连接中断，已下载部分保留，请重试继续。"
                    )
                elif isinstance(exc, httpx.HTTPStatusError):
                    error = QCoreApplication.translate(
                        "Desktop", "下载源暂不可用或拒绝请求，请稍后重试。"
                    )
            if not self._closing:
                self._completed.emit(result, error)

        self._thread = threading.Thread(target=run, name="shinar-speech-library", daemon=True)
        self._thread.start()
        self._timer.start()
        self.progressChanged.emit()
        self.changed.emit()

    @Slot(object, str)
    def _finish(self, result, error):
        if self._closing:
            return
        self._timer.stop()
        self._busy = False
        if result:
            self._hardware = result["hardware"]
            self._rows = result["rows"]
            self._storage_usage = result.get("storageUsage", self._storage_usage)
            if "runtimes" in result:
                self._runtimes = result["runtimes"]
                self.runtimesChanged.emit()
            self.modelsChanged.emit()
        errors = {
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
                "Desktop", "缓存盘空间不足，请按页面的“安装需可用空间”释放空间后重试。"
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
        self._status = error or (
            QCoreApplication.translate("Desktop", "后台下载继续进行，可在任务列表查看每项进度。")
            if self.downloadCount
            else QCoreApplication.translate("Desktop", "模型状态已更新。下载后请先测速，再选用。")
        )
        self.changed.emit()

        if not error and result and result.get("selectAfterBenchmark"):
            model_id, language, scenario = result["selectAfterBenchmark"]
            if (language, scenario) == (self._language, self._scenario):
                self.select(model_id)

        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _snapshot(self):
        hardware = detect_hardware(self.store.root)
        settings = load_compute(self.store.root)
        devices = {}
        for package in self.catalog:
            try:
                devices[package.id] = resolve_device(package, settings, hardware)[0]
            except ValueError:
                devices[package.id] = "cuda"
        rows = model_rows(
            self.store,
            self.catalog,
            self._language,
            self._scenario,
            hardware,
            devices,
            settings.gpu_index,
        )
        for row in rows:
            package = self._package(row["id"])
            row["cacheMiB"] = round(cached_model_bytes(self.store.root, package.files) / 1024**2, 1)
            options = voices(package.id, self.store.root)
            row.update(
                voices=options,
                voiceId=voice_choice(self.store.root, package.id).get("id", ""),
                termsRequired=package.adapter == "voicevox",
                termsAccepted=accepted_terms(self.store.root, package),
                termsUrl="https://github.com/VOICEVOX/voicevox_vvm/blob/0.17.0/README.md",
            )
            row["termsText"] = ""
            if package.adapter == "voicevox":
                from importlib.resources import files

                row["termsText"] = (
                    files("shinar.local_speech")
                    .joinpath("runtime_resources/VOICEVOX-TERMS-0.17.0.txt")
                    .read_text("utf-8")
                )
                row["notes"] = QCoreApplication.translate(
                    "Desktop", "ずんだもん：本轮支持 CPU，需确认模型与角色条款并保留署名。"
                )
                row["deviceNote"] = QCoreApplication.translate(
                    "Desktop", "本轮仅支持 CPU；尚未开放 GPU 加速。"
                )
            elif package.adapter == "melo_english":
                row["notes"] = QCoreApplication.translate(
                    "Desktop", "独立英文：CPU 可用但较慢，CUDA 已验证提速；采用整句合成。"
                )
                row["deviceNote"] = QCoreApplication.translate(
                    "Desktop", "推荐使用已验证的 NVIDIA GPU；实际速度与资源需求以本机测速为准。"
                )
            if package.adapter in {"voicevox", "melo_english"}:
                row["streaming"] = QCoreApplication.translate("Desktop", "按句合成，返回完整音频")
                stats = row["measurementStats"]
                row["measurement"] = QCoreApplication.translate("Desktop", "尚未本机测速")
                if stats:
                    row["measurement"] = (
                        QCoreApplication.translate(
                            "Desktop",
                            "%1 · 热态整句合成平均 %2 / p95 %3 ms · %4 次",
                        )
                        .replace("%1", row["device"].upper())
                        .replace("%2", f"{stats['average_ms']:.0f}")
                        .replace("%3", f"{stats['p95_ms']:.0f}")
                        .replace("%4", str(stats["repeats"]))
                    )
                    if stats["concurrent_p95_ms"] is not None:
                        row["measurement"] += QCoreApplication.translate(
                            "Desktop", "；并发整句合成 p95 %1 ms"
                        ).replace("%1", f"{stats['concurrent_p95_ms']:.0f}")
            try:
                plan = make_plan(self.store.root, package, self._language, devices[package.id])
                native = package.adapter in {"voicevox", "melo_english"}
                status = (
                    managed_status(self.store.root, plan.runtime_id)
                    if native
                    else runtime_status(self.store.root, devices[package.id])
                )
                row.update(
                    runtimeReady=bool(status.get("prepared")),
                    setupMiB=round(plan.download_bytes / 1024**2, 1),
                    setupDiskMiB=round(plan.disk_bytes / 1024**2, 1),
                    setupError="",
                )
            except ValueError:
                row.update(
                    runtimeReady=False,
                    setupMiB=0,
                    setupDiskMiB=0,
                    setupError=QCoreApplication.translate(
                        "Desktop", "当前计算设备不支持此模型，请切换自动或 CPU。"
                    ),
                )
        return {
            "hardware": hardware,
            "rows": rows,
            "runtimes": self._runtime_snapshot(),
            "storageUsage": storage_usage(self.store.root),
        }

    @Slot()
    def refresh(self):
        self._start(QCoreApplication.translate("Desktop", "检测硬件与本地模型…"), self._snapshot)

    @Slot(str, str)
    def setFilter(self, language, scenario):
        if (
            self._busy
            or language not in {"zh", "en", "ja", "ko", "yue", "de", "fr", "es"}
            or scenario not in {"conversation", "import", "reading"}
        ):
            return
        self._language, self._scenario = language, scenario
        self.refresh()

    def _package(self, id):
        return next(p for p in self.catalog if p.id == id)


    @Slot(str)
    def preview(self, id):
        if self._voice_active():
            self._status = QCoreApplication.translate("Desktop", "请先停止语音，再试听模型声音。")
            self.changed.emit()
            return
        row = next((r for r in self._rows if r["id"] == id), {})
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
                    self._status = QCoreApplication.translate(
                        "Desktop", "所选播放设备不可用，请在音频设置中重新选择。"
                    )
                    self.changed.emit()
                    return
                self._audio.setDevice(device)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.play()
            credit = voice_choice(self.store.root, id).get("attribution", "")
            if credit:
                self._status = credit
                self.changed.emit()

    def _playback_error(self):
        self._status = QCoreApplication.translate(
            "Desktop", "试听播放失败，可重新测速生成音频并检查输出设备。"
        )
        self.changed.emit()

    @Slot()
    def stopPreview(self):
        self._player.stop()

    @Slot()
    def cancel(self):
        self._cancel.set()

    @Slot()
    def begin_shutdown(self):
        self._closing = True
        self._downloads.begin_shutdown()
        self._cancel.set()
        self._timer.stop()
        self._resource_timer.stop()
        self._player.stop()

    def finish_shutdown(self) -> bool:
        threads = (self._thread, self._resource_thread)
        return self._downloads.finish_shutdown() and all(thread is None or not thread.is_alive() for thread in threads)

    def close(self):
        self.begin_shutdown()
        self._downloads.close()
        for thread in (self._thread, self._resource_thread):
            if thread:
                thread.join(timeout=0.3)
