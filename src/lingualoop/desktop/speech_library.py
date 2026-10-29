from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

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


class SpeechLibraryViewModel(QObject):
    changed = Signal()
    modelsChanged = Signal()
    progressChanged = Signal()
    _completed = Signal(object, str)
    configurationChanged = Signal()
    inferenceStatus = Signal(str)
    resourcesChanged = Signal()
    _resourcesReady = Signal(object)

    def __init__(self, root=None, parent=None):
        super().__init__(parent)
        self.store = ModelStore(Path(root) if root else default_cache_root())
        self.catalog = load_catalog()
        self._language, self._scenario = "ja", "conversation"
        self._rows, self._hardware = [], {}
        self._busy, self._status, self._operation = False, "点击刷新，检测当前可用资源。", ""
        self._thread, self._cancel = None, threading.Event()
        self._closing = False
        self._progress, self._progress_lock = 0.0, threading.Lock()
        self._completed.connect(self._finish)
        self.local_service = LocalSpeechService(self.store.root, status=self.inferenceStatus.emit)
        self.inferenceStatus.connect(self._inference_status)
        self._resources = {}
        self._resource_thread = None
        self._resourcesReady.connect(self._set_resources)
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

    @Property("QVariantMap", notify=changed)
    def compute(self):
        return load_compute(self.store.root).model_dump()

    @Property("QVariantMap", notify=changed)
    def runtimes(self):
        return {device: runtime_status(self.store.root, device) for device in ("cpu", "cuda")}

    @Property(str, notify=resourcesChanged)
    def resourceSummary(self):
        value = self._resources
        lines = [
            f"GPU {g['index']} · {g['name']} · 整卡显存 {g['used_mb']} / {g['total_mb']} MiB · 整卡使用率 {g['utilization']:.0f}%"
            for g in value.get("gpus", [])
        ]
        used = value.get("speech_process_mb")
        if value:
            lines.append(
                f"本软件语音进程 {value['process_count']} 个 · 显存 "
                + (f"{used} MiB" if used is not None else "驱动未提供进程级读数")
            )
        return "\n".join(lines) or "正在读取资源；当前仅支持 NVIDIA CUDA GPU。"

    @Slot(object)
    def _set_resources(self, value):
        self._resources = value
        self.resourcesChanged.emit()

    @Slot(str)
    def _inference_status(self, value):
        self._status = value
        self.changed.emit()

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
            self._status = "计算设置的数值无效。"
            self.changed.emit()
            return
        save_compute(self.store.root, updated)
        self.local_service.request_release()
        self.configurationChanged.emit()
        self.refresh()

    @Slot(str)
    def prepareRuntime(self, device):
        if device not in {"cpu", "cuda"}:
            return

        def operation():
            install_runtime(
                self.store.root,
                device,
                cancel=self._cancel,
                gpu_index=load_compute(self.store.root).gpu_index,
            )
            return self._snapshot()

        self._start("准备独立运行环境与必要运行库（GPU 下载可能较大）…", operation)

    @Slot(str)
    def checkRuntime(self, device):
        if device not in {"cpu", "cuda"}:
            return

        def operation():
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

        self._start("检查运行环境并执行真实计算探针…", operation)

    @Slot()
    def releaseModels(self):
        self.local_service.request_release()
        self._status = "正在释放空闲模型；运行中的推理会先完成。"
        self.changed.emit()

    @Property("QVariantList", notify=modelsChanged)
    def models(self):
        return self._rows

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
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
            return "尚未检测硬件"
        free = h.get("available_ram_bytes")
        ram = f"{free / 1024**3:.1f} GiB 可用内存" if free else "可用内存未知"
        gpu = "；".join(
            g["name"] + f"（可用 {g['available_mb']} MiB）" for g in h["gpus"]
        )
        return (
            f"{h.get('cpu_name', h['cpu'])} · {h['logical_cpus']} 逻辑核心 · {ram} · 磁盘剩余 {h['disk_free_bytes'] / 1024**3:.1f} GiB"
            + ("\n" + gpu if gpu else "")
        )

    def _start(self, title, operation):
        if self._busy or self._closing:
            return
        self._busy, self._operation, self._status = True, title, title
        self._progress = 0
        self._cancel = threading.Event()
        self._player.stop()

        def run():
            try:
                result = operation()
                error = ""
            except DownloadCancelled as exc:
                result, error = None, str(exc)
            except Exception as exc:
                result, error = (
                    None,
                    (
                        str(exc)
                        if isinstance(exc, (ValueError, RuntimeError))
                        else "操作未完成，请检查网络、磁盘与本地运行依赖后重试。"
                    ),
                )
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
            self.modelsChanged.emit()
        self._status = error or "完成。测速仅含本地计算；尚未验证真人语音与完整对话延迟。"
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
        return {
            "hardware": hardware,
            "rows": model_rows(
                self.store, self.catalog, self._language, self._scenario, hardware, devices, settings.gpu_index
            ),
        }

    @Slot()
    def refresh(self):
        self._start("检测硬件与本地模型…", self._snapshot)

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

        self._start("下载并校验模型…", operation)

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

        self._start("卸载模型…", operation)

    @Slot(str)
    def verify(self, id):
        def operation():
            self.store.verify(self._package(id), cancel=self._cancel)
            return self._snapshot()

        self._start("校验本地文件…", operation)

    @Slot(str, str)
    def runBenchmark(self, id, wav):
        def operation():
            package = self._package(id)
            settings = load_compute(self.store.root)
            device, _ = resolve_device(package, settings, detect_hardware(self.store.root))
            python = runtime_python(self.store.root, device)
            if not runtime_status(self.store.root, device).get("prepared"):
                if device == "cuda" or package.adapter == "sensevoice-ort":
                    raise ValueError("请先在计算与加速中准备对应运行环境。")
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
            )
            return self._snapshot()

        self._start("独立进程测速（含预热与 5 次热态）…", operation)

    @Slot(str)
    def runPairBenchmark(self, wav):
        def operation():
            selections = read_json(self.store.root / "selections.json", {})
            packages = []
            for task in ("stt", "tts"):
                selected = selections.get(f"{self._language}:{self._scenario}:{task}")
                if not selected:
                    raise ValueError("请先测速并保存本语言的 STT 与 TTS 候选。")
                package = self._package(selected["id"])
                if selected.get("fingerprint") != package.fingerprint:
                    raise ValueError("模型已更新，请重新测速选择。")
                if selected.get("runtime_version") != runtime_version(package):
                    raise ValueError("运行时已更新，请重新测速选择。")
                if selected.get("adapter_revision", 1) != adapter_revision(package.adapter):
                    raise ValueError("模型加载配置已更新，请重新测速选择。")
                packages.append(package)
            settings = load_compute(self.store.root)
            hardware = detect_hardware(self.store.root)
            devices = {p.id: resolve_device(p, settings, hardware)[0] for p in packages}
            device = "cuda" if "cuda" in devices.values() else "cpu"
            python = runtime_python(self.store.root, device)
            if not runtime_status(self.store.root, device).get("prepared"):
                raise ValueError("请先准备所选计算设备的运行环境。")
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
            )
            return self._snapshot()

        self._start("STT + TTS 同时运行测速…", operation)

    @Slot(str)
    def select(self, id):
        if self._busy:
            return
        package = self._package(id)
        row = next((r for r in self._rows if r["id"] == id), {})
        if not row.get("measured") or not row.get("installed"):
            return
        if row.get("excluded"):
            self._status = "此配置已在严格评测与试听中排除，请选择其他模型。"
            self.changed.emit()
            return
        if (
            package.task == "stt"
            and self._scenario == "conversation"
            and not row.get("withinRealtimeBudget")
        ):
            self._status = "此模型在当前设备上平均超过 500 ms，请改用 GPU 测速或选择其他识别模型。"
            self.changed.emit()
            return
        selected = read_json(self.store.root / "selections.json", {})
        selected[f"{self._language}:{self._scenario}:{package.task}"] = {
            "id": id,
            "fingerprint": package.fingerprint,
            "runtime_version": runtime_version(package),
            "adapter_revision": adapter_revision(package.adapter),
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
        self._status = (
            "已保存本语言的模型；实时对话选择会用于桌面分轮语音，下次推理按计算设置运行。"
        )
        self.changed.emit()

    @Slot(str)
    def preview(self, id):
        row = next((r for r in self._rows if r["id"] == id), {})
        path = Path(row.get("preview") or "")
        if path.is_file() and path.resolve().is_relative_to(
            (self.store.root / "reports").resolve()
        ):
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.play()

    def _playback_error(self):
        self._status = "试听播放失败，可重新测速生成音频并检查输出设备。"
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
