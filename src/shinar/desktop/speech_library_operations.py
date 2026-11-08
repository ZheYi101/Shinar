"""Installation and benchmarking actions for the speech-library facade."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl, Signal, Slot

from shinar.local_speech import adapter_revision
from shinar.local_speech.benchmark import benchmark
from shinar.local_speech.hardware import detect_hardware
from shinar.local_speech.storage import atomic_json, read_json
from shinar.local_speech.compute import (
    load_compute,
    save_compute,
    resolve_device,
    runtime_version,
)
from shinar.local_speech.runtime import (
    probe_runtime,
    runtime_python,
    runtime_status,
)
from shinar.local_speech.installation import (
    make_plan,
    managed_status,
    probe_managed_runtime,
)
from shinar.local_speech.model_profile import (
    accepted_terms,
    build_profile,
    voice_choice,
    voices,
)
from shinar.local_speech.samples import benchmark_audio
from shinar.infrastructure.blocking_jobs import prepare_runtime_owned as prepare_managed_runtime


class SpeechLibraryOperations:
    changed = Signal()

    statusChanged = Signal()

    runtimesChanged = Signal()

    modelsChanged = Signal()

    progressChanged = Signal()

    downloadsChanged = Signal()

    _completed = Signal(object, str)

    configurationChanged = Signal()

    inferenceStatus = Signal(str)

    resourcesChanged = Signal()

    _resourcesReady = Signal(object)

    _setupStage = Signal(str)

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

    @Slot(str)
    def install(self, id):
        self._enqueue_preparation(id, with_runtime=False)

    @Slot(str)
    def preparePackage(self, id):
        self._enqueue_preparation(id, with_runtime=True)

    def _enqueue_preparation(self, id, *, with_runtime):
        package, language = self._package(id), self._language
        settings = load_compute(self.store.root)

        def operation(cancel, stage, transfer):
            if not accepted_terms(self.store.root, package):
                raise ValueError("speech_voice_terms_required")
            hardware = detect_hardware(self.store.root)
            device, _ = resolve_device(package, settings, hardware)
            plan = make_plan(self.store.root, package, language, device)
            import shutil

            self.store.root.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.store.root).free < plan.disk_bytes:
                raise ValueError("speech_setup_disk_insufficient")
            # Model files can download concurrently even if two jobs need the
            # same environment. Shared blobs and runtime preparation wait safely.
            stage("speech_setup_model")
            self.store.install(
                package,
                cancel=cancel,
                wait_for_locks=True,
                on_transfer=transfer,
            )
            if with_runtime:
                prepare_managed_runtime(
                    self.store.root,
                    plan.runtime_id,
                    cancel=cancel,
                    stage=stage,
                    on_transfer=transfer,
                    wait_for_locks=True,
                    gpu_index=settings.gpu_index,
                )

        self._downloads.enqueue(package.id, package.name, package.task, language, operation)

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
        self._run_benchmark(id, wav)

    @Slot(str)
    def benchmarkAndSelect(self, id):
        self._run_benchmark(id, "", select_after=True)

    def _run_benchmark(self, id, wav, *, select_after=False):
        package, language, scenario = self._package(id), self._language, self._scenario
        settings = load_compute(self.store.root)

        def operation():
            device, _ = resolve_device(package, settings, detect_hardware(self.store.root))
            python = runtime_python(self.store.root, device)
            profiles = None
            if package.adapter in {"voicevox", "melo_english"}:
                profiles = {
                    id: build_profile(
                        self.store,
                        package,
                        language,
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
            audio = (
                benchmark_audio(language, QUrl(wav).toLocalFile() if wav else None)
                if package.task == "stt" else nullcontext(None)
            )
            with audio as sample:
                benchmark(
                    self.store, [package], language, wav=sample,
                    cancel=self._cancel, python=python, devices={id: device},
                    gpu_index=settings.gpu_index, vram_budget_mb=settings.vram_budget_mb,
                    profiles=profiles,
                )
            result = self._snapshot()
            if select_after:
                result["selectAfterBenchmark"] = (id, language, scenario)
            return result

        self._start(
            QCoreApplication.translate("Desktop", "使用内置示例测速（含预热与 5 次热态）…")
            if not wav else QCoreApplication.translate("Desktop", "使用所选录音测速（含预热与 5 次热态）…"),
            operation,
        )

    @Slot(str)
    def runPairBenchmark(self, wav):
        language, scenario = self._language, self._scenario

        def operation():
            selections = read_json(self.store.root / "selections.json", {})
            packages = []
            for task in ("stt", "tts"):
                selected = selections.get(f"{language}:{scenario}:{task}")
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
            with benchmark_audio(language, QUrl(wav).toLocalFile() if wav else None) as sample:
                benchmark(
                    self.store, packages, language, wav=sample,
                    cancel=self._cancel, python=python, devices=devices,
                    gpu_index=settings.gpu_index, vram_budget_mb=settings.vram_budget_mb,
                    profiles={
                        p.id: build_profile(
                            self.store, p, language, devices[p.id],
                            gpu_index=settings.gpu_index,
                            vram_budget_mb=settings.vram_budget_mb,
                        ) for p in packages
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



