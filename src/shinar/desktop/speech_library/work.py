"""Blocking operations on a request frozen before leaving the Qt thread."""

from contextlib import nullcontext
from pathlib import Path
from shinar.local_speech import adapter_revision
from shinar.local_speech.benchmark import benchmark
from shinar.local_speech.hardware import detect_hardware
from shinar.local_speech.storage import atomic_json, read_json
from shinar.local_speech.storage_lease import storage_lease
from shinar.local_speech.compute import resolve_device, runtime_version
from shinar.local_speech.runtime import probe_runtime, runtime_python, runtime_status
from shinar.local_speech.installation import (
    make_plan,
    managed_status,
    probe_managed_runtime,
    runtime_plan,
)
from shinar.local_speech.model_profile import accepted_terms, build_profile, voice_choice, voices
from shinar.local_speech.samples import benchmark_audio
from shinar.infrastructure.blocking_jobs import prepare_runtime_owned as prepare_managed_runtime
from shinar.local_speech.catalog import ModelPackage
from shinar.local_speech.compute import ComputeSettings
from shinar.local_speech.library import model_rows
from shinar.local_speech.usage import cached_model_bytes, storage_usage


class LibraryWork:
    def __init__(self, request, store_factory, cancel, emit):
        self.store = store_factory(request.root)
        self.catalog = tuple((ModelPackage.model_validate_json(value) for value in request.catalog))
        self._language, self._scenario = (request.language, request.scenario)
        self.settings = ComputeSettings.model_validate_json(request.settings)
        self._cancel, self.emit = (cancel, emit)

    def _package(self, identity):
        return next((p for p in self.catalog if p.id == identity))

    def _download_progress(self, done, total):
        self.emit("progress", (done, total))

    def execute(self, kind, args, kwargs):
        with storage_lease(self.store.root, cancel=self._cancel):
            return getattr(self, kind)(*args, **kwargs)

    def prepareRuntime(self, device):
        if device not in {"cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu"}:
            return

        def operation():
            prepare_managed_runtime(
                self.store.root,
                "ort-" + device if device in {"cpu", "cuda"} else device,
                cancel=self._cancel,
                gpu_index=self.settings.gpu_index,
                repair=True,
                progress=self._download_progress,
                stage=lambda value: self.emit("stage", value),
            )
            return self._snapshot()

        return operation()

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
                    gpu_index=self.settings.gpu_index,
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
                gpu_index=self.settings.gpu_index,
                cancel=self._cancel,
            )
            atomic_json(
                Path(runtime_python(self.store.root, device)).parent.parent / "ready.json", result
            )
            return self._snapshot()

        return operation()

    def preparation_operation(self, id, *, with_runtime):
        package, language = (self._package(id), self._language)
        settings = self.settings

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
            stage("speech_setup_model")
            self.store.install(package, cancel=cancel, wait_for_locks=True, on_transfer=transfer)
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

        def leased_operation(cancel, stage, transfer):
            with storage_lease(self.store.root, wait=True, cancel=cancel):
                return operation(cancel, stage, transfer)

        return leased_operation

    def uninstall(self, id):

        def operation():
            self.store.uninstall(self._package(id))
            selections = read_json(self.store.root / "selections.json", {})
            atomic_json(
                self.store.root / "selections.json",
                {k: v for k, v in selections.items() if v.get("id") != id},
            )
            return self._snapshot()

        return operation()

    def verify(self, id):

        def operation():
            self.store.verify(self._package(id), cancel=self._cancel)
            return self._snapshot()

        return operation()

    def _run_benchmark(self, id, wav, *, select_after=False):
        package, language, scenario = (self._package(id), self._language, self._scenario)
        settings = self.settings

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
            if profiles is None and (not runtime_status(self.store.root, device).get("prepared")):
                if device == "cuda" or package.adapter == "sensevoice-ort":
                    raise ValueError("library_message_1")
                python = None
            audio = (
                benchmark_audio(language, wav if wav else None)
                if package.task == "stt"
                else nullcontext(None)
            )
            with audio as sample:
                benchmark(
                    self.store,
                    [package],
                    language,
                    wav=sample,
                    cancel=self._cancel,
                    python=python,
                    devices={id: device},
                    gpu_index=settings.gpu_index,
                    vram_budget_mb=settings.vram_budget_mb,
                    profiles=profiles,
                )
            result = self._snapshot()
            if select_after:
                result["selectAfterBenchmark"] = (id, language, scenario)
            return result

        return operation()

    def runPairBenchmark(self, wav):
        language, scenario = (self._language, self._scenario)

        def operation():
            selections = read_json(self.store.root / "selections.json", {})
            packages = []
            for task in ("stt", "tts"):
                selected = selections.get(f"{language}:{scenario}:{task}")
                if not selected:
                    raise ValueError("library_message_2")
                package = self._package(selected["id"])
                if selected.get("fingerprint") != package.fingerprint:
                    raise ValueError("library_message_3")
                if selected.get("runtime_version") != runtime_version(package):
                    raise ValueError("library_message_4")
                if selected.get("adapter_revision", 1) != adapter_revision(package.adapter):
                    raise ValueError("library_message_5")
                packages.append(package)
            settings = self.settings
            hardware = detect_hardware(self.store.root)
            devices = {p.id: resolve_device(p, settings, hardware)[0] for p in packages}
            device = "cuda" if "cuda" in devices.values() else "cpu"
            python = runtime_python(self.store.root, device)
            if not any((p.adapter in {"voicevox", "melo_english"} for p in packages)) and (
                not runtime_status(self.store.root, device).get("prepared")
            ):
                raise ValueError("library_message_6")
            with benchmark_audio(language, wav if wav else None) as sample:
                benchmark(
                    self.store,
                    packages,
                    language,
                    wav=sample,
                    cancel=self._cancel,
                    python=python,
                    devices=devices,
                    gpu_index=settings.gpu_index,
                    vram_budget_mb=settings.vram_budget_mb,
                    profiles={
                        p.id: build_profile(
                            self.store,
                            p,
                            language,
                            devices[p.id],
                            gpu_index=settings.gpu_index,
                            vram_budget_mb=settings.vram_budget_mb,
                        )
                        for p in packages
                    },
                )
            return self._snapshot()

        return operation()

    def _runtime_snapshot(self):
        values = {
            **{device: runtime_status(self.store.root, device) for device in ("cpu", "cuda")},
            **{
                name: managed_status(self.store.root, name)
                for name in ("voicevox-cpu", "melo-cpu", "melo-cuda", "rtc-cpu")
            },
        }
        index = self.settings.gpu_index
        for name, value in values.items():
            if "cuda" in name and value.get("gpu_index", index) != index:
                value["prepared"] = False
            plan = runtime_plan(self.store.root, "ort-" + name if name in {"cpu", "cuda"} else name)
            value.update(
                downloadMiB=round(plan.download_bytes / 1024**2, 1),
                diskMiB=round(plan.disk_bytes / 1024**2, 1),
            )
        return values

    def _snapshot(self):
        hardware = detect_hardware(self.store.root)
        settings = self.settings
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
            row["_adapter"] = package.adapter
            if package.adapter == "voicevox":
                from importlib.resources import files

                row["termsText"] = (
                    files("shinar.local_speech")
                    .joinpath("runtime_resources/VOICEVOX-TERMS-0.17.0.txt")
                    .read_text("utf-8")
                )
            row["cacheMiB"] = round(cached_model_bytes(self.store.root, package.files) / 1024**2, 1)
            options = voices(package.id, self.store.root)
            row.update(
                voices=options,
                voiceId=voice_choice(self.store.root, package.id).get("id", ""),
                termsRequired=package.adapter == "voicevox",
                termsAccepted=accepted_terms(self.store.root, package),
                termsUrl="https://github.com/VOICEVOX/voicevox_vvm/blob/0.17.0/README.md",
            )
            if package.adapter != "voicevox":
                row["termsText"] = ""
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
                    runtimeReady=False, setupMiB=0, setupDiskMiB=0, setupError="library_message_7"
                )
        return {
            "hardware": hardware,
            "rows": rows,
            "runtimes": self._runtime_snapshot(),
            "storageUsage": storage_usage(self.store.root),
        }
