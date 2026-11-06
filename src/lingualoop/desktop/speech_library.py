from __future__ import annotations

import threading
import re
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaDevices

from lingualoop.local_speech import RUNTIME_VERSION, adapter_revision
from lingualoop.local_speech.benchmark import benchmark
from lingualoop.local_speech.catalog import load_catalog
from lingualoop.local_speech.downloads import DownloadCancelled, ModelStore
from lingualoop.local_speech.hardware import admission, detect_hardware
from lingualoop.local_speech.library import model_rows
from lingualoop.local_speech.storage import atomic_json, default_cache_root, read_json
from lingualoop.local_speech.compute import (
    load_compute,
    save_compute,
    resolve_device,
    runtime_version,
)
from lingualoop.local_speech.runtime import (
    install_runtime,
    probe_runtime,
    runtime_python,
    runtime_status,
)
from lingualoop.local_speech.resources import resource_snapshot
from lingualoop.local_speech.service import LocalSpeechService
from lingualoop.local_speech.installation import (
    make_plan,
    managed_status,
    prepare_managed_runtime,
    probe_managed_runtime,
    runtime_id_for,
    runtime_plan,
)
from lingualoop.local_speech.model_profile import (
    accepted_terms,
    build_profile,
    voice_choice,
    voices,
)


class SpeechLibraryViewModel(QObject):
    changed = Signal()
    statusChanged = Signal()
    runtimesChanged = Signal()
    modelsChanged = Signal()
    progressChanged = Signal()
    _completed = Signal(object, str)
    configurationChanged = Signal()
    inferenceStatus = Signal(str)
    resourcesChanged = Signal()
    _resourcesReady = Signal(object)
    _setupStage = Signal(str)

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.store = ModelStore(Path(root) if root else default_cache_root())
        self.catalog = load_catalog()
        self._language, self._scenario = "ja", "conversation"
        self._rows, self._hardware = [], {}
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

    def configure_preview(self, device_id: Callable[[], str], voice_active: Callable[[], bool]) -> None:
        """GUI-only device getters; never change devices or add preview echo during a call."""
        self._preview_device, self._voice_active = device_id, voice_active

    @Property("QVariantMap", notify=changed)
    def compute(self):
        return load_compute(self.store.root).model_dump()

    @Property("QVariantMap", notify=changed)
    def lastSetupError(self):
        return self._last_setup_error

    @Property("QVariantMap", notify=runtimesChanged)
    def runtimes(self):
        # QML reads this once for each binding/delegate, including hidden pages.
        # File verification and installation planning belong to the library worker.
        return self._runtimes

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
            value.update(downloadMiB=round(plan.download_bytes / 1024**2, 1),
                         diskMiB=round(plan.disk_bytes / 1024**2, 1))
        return values

    @Slot(str)
    def _setup_status(self, stage):
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

    @Property(str, notify=resourcesChanged)
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

    @Slot(str, "QVariant")
    def setCompute(self, name, value):
        if self._busy or name not in type(load_compute(self.store.root)).model_fields:
            return
        try:
            settings = load_compute(self.store.root)
            updated = type(settings).model_validate({**settings.model_dump(), name: value})
        except ValueError:
            self._status = QCoreApplication.translate("Desktop", "计算设置的数值无效。")
            self.changed.emit()
            return
        save_compute(self.store.root, updated)
        self.local_service.request_release()
        self.configurationChanged.emit()
        self.refresh()

    @Slot(str)
    def prepareRuntime(self, device):
        if device not in {"cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu"}:
            return
        if self.local_service.pids:
            self._status = QCoreApplication.translate(
                "Desktop", "请先停止语音并释放已加载模型，再修复运行环境。"
            )
            self.changed.emit()
            return

        def operation():
            prepare_managed_runtime(
                self.store.root,
                "ort-" + device if device in {"cpu", "cuda"} else device,
                cancel=self._cancel,
                gpu_index=load_compute(self.store.root).gpu_index,
                repair=True,
                progress=self._download_progress,
                stage=self._setupStage.emit,
            )
            return self._snapshot()

        self._start(
            QCoreApplication.translate(
                "Desktop", "准备独立运行环境与必要运行库（GPU 下载可能较大）…"
            ),
            operation,
        )

    @Slot(str)
    def checkRuntime(self, device):
        if device not in {"cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu"}:
            return

        def operation():
            if device not in {"cpu", "cuda"}:
                status = managed_status(self.store.root, device)
                if not status.get("prepared"):
                    raise ValueError("speech_runtime_not_ready")
                result = probe_managed_runtime(
                    self.store.root,
                    device,
                    status["python"],
                    gpu_index=load_compute(self.store.root).gpu_index,
                    cancel=self._cancel,
                )
                if result.get("ok") is not True:
                    raise ValueError("speech_runtime_probe_failed")
                marker = Path(status["python"]).parent.parent / "ready.json"
                atomic_json(marker, {**read_json(marker, {}), **result})
                return self._snapshot()
            result = probe_runtime(
                runtime_python(self.store.root, device),
                device,
                gpu_index=load_compute(self.store.root).gpu_index,
                cancel=self._cancel,
            )
            atomic_json(
                Path(runtime_python(self.store.root, device)).parent.parent / "ready.json", result
            )
            return self._snapshot()

        self._start(
            QCoreApplication.translate("Desktop", "检查运行环境并执行真实计算探针…"), operation
        )

    @Slot()
    def releaseModels(self):
        self.local_service.request_release()
        self._status = QCoreApplication.translate(
            "Desktop", "正在释放空闲模型；运行中的推理会先完成。"
        )
        self.changed.emit()

    @Property("QVariantList", notify=modelsChanged)
    def models(self):
        return self._rows

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(str, notify=changed)
    def language(self):
        return self._language

    @Property(str, notify=changed)
    def scenario(self):
        return self._scenario

    @Property(str, notify=changed)
    def operation(self):
        return self._operation

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._progress

    @Property(str, notify=changed)
    def cachePath(self):
        return str(self.store.root)

    @Property(str, notify=changed)
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
                self._last_setup_error = {"type": type(exc).__name__,
                    "code": str(exc) if re.fullmatch(r"speech_[a-z_]+", str(exc)) else "speech_setup_failed"}
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
                    error = QCoreApplication.translate("Desktop", "下载连接中断，已下载部分保留，请重试继续。")
                elif isinstance(exc, httpx.HTTPStatusError):
                    error = QCoreApplication.translate("Desktop", "下载源暂不可用或拒绝请求，请稍后重试。")
            if not self._closing:
                self._completed.emit(result, error)

        self._thread = threading.Thread(target=run, name="lingualoop-speech-library", daemon=True)
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
                "Desktop", "缓存盘空间不足，请释放页面所示准备空间后重试。"
            ),
            "speech_voice_invalid": QCoreApplication.translate(
                "Desktop", "声音选项无效，请重新选择。"
            ),
            "speech_setup_cancelled": QCoreApplication.translate(
                "Desktop", "准备已取消，已校验下载保留，可继续。"
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
        self._status = error or QCoreApplication.translate(
            "Desktop", "完成。测速仅含本地计算；尚未验证真人语音与完整对话延迟。"
        )
        self.changed.emit()

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
                    files("lingualoop.local_speech")
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
                    row["measurement"] = QCoreApplication.translate(
                        "Desktop", "%1 · 热态整句合成平均 %2 / p95 %3 ms · 进程内存 %4 MiB · %5 次"
                    ).replace("%1", row["device"].upper()).replace("%2", f"{stats['average_ms']:.0f}").replace("%3", f"{stats['p95_ms']:.0f}").replace("%4", f"{stats['peak_mib']:.0f}").replace("%5", str(stats["repeats"]))
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
    def install(self, id):
        def operation():
            package = self._package(id)
            allowed, reason = admission(package, detect_hardware(self.store.root))
            if not allowed:
                raise ValueError(reason)

            def progress(done, total):
                with self._progress_lock:
                    self._progress = done / total

            self.store.install(package, cancel=self._cancel, progress=progress)
            return self._snapshot()

        self._start(QCoreApplication.translate("Desktop", "下载并校验模型…"), operation)

    @Slot(str)
    def preparePackage(self, id):
        package, language = self._package(id), self._language
        settings = load_compute(self.store.root)

        def operation():
            if not accepted_terms(self.store.root, package):
                raise ValueError("speech_voice_terms_required")
            hardware = detect_hardware(self.store.root)
            device, _ = resolve_device(package, settings, hardware)
            plan = make_plan(self.store.root, package, language, device)
            import shutil

            self.store.root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.store.root).free < plan.disk_bytes:
                raise ValueError(
                    QCoreApplication.translate("Desktop", "磁盘空间不足，无法完成环境与模型准备。")
                )
            prepare_managed_runtime(
                self.store.root,
                plan.runtime_id,
                cancel=self._cancel,
                progress=self._download_progress,
                stage=self._setupStage.emit,
                gpu_index=settings.gpu_index,
            )
            self._setupStage.emit("speech_setup_model")
            self.store.install(package, cancel=self._cancel, progress=self._download_progress)
            return self._snapshot()

        self._start(QCoreApplication.translate("Desktop", "准备环境与模型…"), operation)

    @Slot(str, bool)
    def acceptVoiceTerms(self, id, accepted):
        if self._busy:
            return
        package = self._package(id)
        data = read_json(self.store.root / "voice-terms.json", {})
        if accepted:
            data[id] = package.fingerprint
        else:
            data.pop(id, None)
        atomic_json(self.store.root / "voice-terms.json", data)
        self.refresh()

    @Slot(str, str)
    def selectVoice(self, id, voice_id):
        if self._busy or not any(v["id"] == voice_id for v in voices(id)):
            return
        data = read_json(self.store.root / "voices.json", {})
        data[id] = voice_id
        atomic_json(self.store.root / "voices.json", data)
        self.refresh()

    @Slot(str)
    def uninstall(self, id):
        def operation():
            self.store.uninstall(self._package(id))
            selections = read_json(self.store.root / "selections.json", {})
            atomic_json(
                self.store.root / "selections.json",
                {k: v for k, v in selections.items() if v.get("id") != id},
            )
            return self._snapshot()

        self._start(QCoreApplication.translate("Desktop", "卸载模型…"), operation)

    @Slot(str)
    def verify(self, id):
        def operation():
            self.store.verify(self._package(id), cancel=self._cancel)
            return self._snapshot()

        self._start(QCoreApplication.translate("Desktop", "校验本地文件…"), operation)

    @Slot(str, str)
    def runBenchmark(self, id, wav):
        def operation():
            package = self._package(id)
            settings = load_compute(self.store.root)
            device, _ = resolve_device(package, settings, detect_hardware(self.store.root))
            python = runtime_python(self.store.root, device)
            profiles = None
            if package.adapter in {"voicevox", "melo_english"}:
                profiles = {
                    id: build_profile(
                        self.store,
                        package,
                        self._language,
                        device,
                        gpu_index=settings.gpu_index,
                        vram_budget_mb=settings.vram_budget_mb,
                    )
                }
                python = profiles[id].python
            if profiles is None and not runtime_status(self.store.root, device).get("prepared"):
                if device == "cuda" or package.adapter == "sensevoice-ort":
                    raise ValueError(
                        QCoreApplication.translate(
                            "Desktop", "请先在计算与加速中准备对应运行环境。"
                        )
                    )
                python = None
            benchmark(
                self.store,
                [self._package(id)],
                self._language,
                wav=QUrl(wav).toLocalFile() if wav else None,
                cancel=self._cancel,
                python=python,
                devices={id: device},
                gpu_index=settings.gpu_index,
                vram_budget_mb=settings.vram_budget_mb,
                profiles=profiles,
            )
            return self._snapshot()

        self._start(
            QCoreApplication.translate("Desktop", "独立进程测速（含预热与 5 次热态）…"), operation
        )

    @Slot(str)
    def runPairBenchmark(self, wav):
        def operation():
            selections = read_json(self.store.root / "selections.json", {})
            packages = []
            for task in ("stt", "tts"):
                selected = selections.get(f"{self._language}:{self._scenario}:{task}")
                if not selected:
                    raise ValueError(
                        QCoreApplication.translate(
                            "Desktop", "请先测速并保存本语言的 STT 与 TTS 候选。"
                        )
                    )
                package = self._package(selected["id"])
                if selected.get("fingerprint") != package.fingerprint:
                    raise ValueError(
                        QCoreApplication.translate("Desktop", "模型已更新，请重新测速选择。")
                    )
                if selected.get("runtime_version") != runtime_version(package):
                    raise ValueError(
                        QCoreApplication.translate("Desktop", "运行时已更新，请重新测速选择。")
                    )
                if selected.get("adapter_revision", 1) != adapter_revision(package.adapter):
                    raise ValueError(
                        QCoreApplication.translate(
                            "Desktop", "模型加载配置已更新，请重新测速选择。"
                        )
                    )
                packages.append(package)
            settings = load_compute(self.store.root)
            hardware = detect_hardware(self.store.root)
            devices = {p.id: resolve_device(p, settings, hardware)[0] for p in packages}
            device = "cuda" if "cuda" in devices.values() else "cpu"
            python = runtime_python(self.store.root, device)
            if not any(
                p.adapter in {"voicevox", "melo_english"} for p in packages
            ) and not runtime_status(self.store.root, device).get("prepared"):
                raise ValueError(
                    QCoreApplication.translate("Desktop", "请先准备所选计算设备的运行环境。")
                )
            benchmark(
                self.store,
                packages,
                self._language,
                wav=QUrl(wav).toLocalFile(),
                cancel=self._cancel,
                python=python,
                devices=devices,
                gpu_index=settings.gpu_index,
                vram_budget_mb=settings.vram_budget_mb,
                profiles={
                    p.id: build_profile(
                        self.store,
                        p,
                        self._language,
                        devices[p.id],
                        gpu_index=settings.gpu_index,
                        vram_budget_mb=settings.vram_budget_mb,
                    )
                    for p in packages
                },
            )
            return self._snapshot()

        self._start(QCoreApplication.translate("Desktop", "STT + TTS 同时运行测速…"), operation)

    @Slot(str)
    def select(self, id):
        if self._busy:
            return
        package = self._package(id)
        row = next((r for r in self._rows if r["id"] == id), {})
        if not row.get("measured") or not row.get("installed"):
            return
        if row.get("excluded"):
            self._status = QCoreApplication.translate(
                "Desktop", "此配置已在严格评测与试听中排除，请选择其他模型。"
            )
            self.changed.emit()
            return
        if (
            package.task == "stt"
            and self._scenario == "conversation"
            and not row.get("withinRealtimeBudget")
        ):
            self._status = QCoreApplication.translate(
                "Desktop", "此模型在当前设备上平均超过 500 ms，请改用 GPU 测速或选择其他识别模型。"
            )
            self.changed.emit()
            return
        selected = read_json(self.store.root / "selections.json", {})
        selected[f"{self._language}:{self._scenario}:{package.task}"] = {
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
        atomic_json(self.store.root / "selections.json", selected)
        if self._scenario == "conversation":
            settings = load_compute(self.store.root)
            save_compute(
                self.store.root, settings.model_copy(update={f"local_{package.task}": True})
            )
            self.local_service.request_release()
            self.configurationChanged.emit()
        for item in self._rows:
            if item["task"].lower() == package.task:
                item["selected"] = item["id"] == id
        self.modelsChanged.emit()
        self._status = QCoreApplication.translate(
            "Desktop",
            "已保存本语言的模型；后续语音按计算设置绑定，当前轮次保留原配置，连续语音需重新开始。",
        )
        self.changed.emit()

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
                device = next((d for d in QMediaDevices.audioOutputs()
                               if bytes(d.id()).hex() == selected), None)
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
    def close(self):
        self._closing = True
        self._cancel.set()
        self._timer.stop()
        self._resource_timer.stop()
        self._player.stop()
        if self._thread:
            self._thread.join(timeout=0.3)
