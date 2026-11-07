"""Async resident providers for the existing Qt turn-based audio path."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import time
import threading
from contextlib import nullcontext
from .profiles import LocalSpeechProfile, instance_key, LocalSpeechProvider

from .catalog import load_catalog
from .compute import device_profile, load_compute, resolve_device
from .downloads import ModelStore, package_lock
from .hardware import detect_hardware
from .runtime import child_environment, runtime_python, runtime_status
from .storage import read_json
from .library import matching_reports
from . import adapter_revision
from .processes import terminate_tree


class LocalSpeechService:
    def __init__(self, root: Path, *, status=None):
        self.store = ModelStore(root)
        self.catalog = {p.id: p for p in load_catalog()}
        self._processes, self._specs, self._last_used, self._locks = {}, {}, {}, {}
        self._reaper = None
        self._status = status or (lambda _: None)
        self._release_requested = threading.Event()
        self._package_locks = {}
        self._actual_pids = {}
        self._registered = {}
        self._verified = {}
        self._admission_lock = asyncio.Lock()
        self.last_metrics = {}

    def provider(self, task: str) -> LocalSpeechProvider:
        if task not in {"stt", "tts"}:
            raise ValueError("invalid_speech_task")
        return LocalSpeechProvider(self, task)

    def register_prepared(self, profile: LocalSpeechProfile) -> None:
        profile.validate_assets()
        self._registered[(profile.task, profile.language)] = profile

    def _vram(self, spec: dict) -> int:
        package = self.catalog.get(spec["id"])
        return device_profile(package)["vram_mb"] if package else spec.get("vram_estimate_mb", 0)

    async def _admit(self, task: str, spec: dict) -> None:
        hardware = await asyncio.to_thread(detect_hardware, self.store.root)
        settings = load_compute(self.store.root)
        available_ram = hardware.get("available_ram_bytes")
        if available_ram is not None and available_ram < (spec.get("ram_estimate_mb", 512) + 2048) * 1024**2:
            raise ValueError("speech_ram_budget_exceeded")
        if spec.get("provider") == "cuda":
            needed = self._vram(spec)
            occupied = sum(self._vram(other) for name, other in self._specs.items()
                           if name != task and other.get("provider") == "cuda")
            cards = hardware.get("gpus", [])
            index = spec.get("gpu_index", 0)
            if (needed <= 0 or index >= len(cards) or occupied + needed > settings.vram_budget_mb
                or cards[index]["available_mb"] < needed + settings.reserve_vram_mb):
                raise ValueError("speech_vram_budget_exceeded")

    def request_release(self) -> None:
        if not self.pids:
            self._release_requested.clear()
            self._status("当前没有驻留的本地语音模型。")
        else:
            self._release_requested.set()

    @property
    def pids(self) -> list[int]:
        return [
            self._actual_pids.get(task, p.pid)
            for task, p in list(self._processes.items())
            if p.returncode is None
        ]

    def worker_pid(self, task: str) -> int | None:
        """Return the actual inference PID, rather than the venv redirector."""
        process = self._processes.get(task)
        if process is None or process.returncode is not None:
            return None
        return self._actual_pids.get(task, process.pid)

    def enabled(self, task: str) -> bool:
        return getattr(load_compute(self.store.root), f"local_{task}")

    @property
    def gpu_pids(self) -> list[int]:
        return [
            self._actual_pids.get(task, p.pid)
            for task, p in list(self._processes.items())
            if p.returncode is None and self._specs.get(task, {}).get("provider") == "cuda"
        ]

    async def _stop(self, task: str) -> None:
        self._verified.pop(task, None)
        process = self._processes.pop(task, None)
        self._actual_pids.pop(task, None)
        self._specs.pop(task, None)
        if process and process.returncode is None:
            await asyncio.to_thread(terminate_tree, process.pid)
            await process.wait()
        if process:
            if process.stdin:
                process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            transport = getattr(process, "_transport", None)
            if transport:
                transport.close()
        held = self._package_locks.pop(task, None)
        if held:
            held.__exit__(None, None, None)

    async def release(self) -> None:
        for task in ("stt", "tts"):
            async with self._locks.setdefault(task, asyncio.Lock()):
                await self._stop(task)
        self._release_requested.clear()
        self._status("本地语音模型已释放；下次使用会重新加载。")

    async def close(self) -> None:
        if self._reaper:
            reaper = self._reaper
            self._reaper = None
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
        await self.release()

    async def _idle(self) -> None:
        while True:
            await asyncio.sleep(2)
            settings = load_compute(self.store.root)
            release_requested = self._release_requested.is_set()
            for task in list(self._processes):
                lock = self._locks[task]
                if not lock.locked() and (
                    release_requested
                    or time.monotonic() - self._last_used.get(task, 0) >= settings.idle_seconds
                ):
                    async with lock:
                        await self._stop(task)
                    self._status("空闲语音模型已释放；下次使用会重新加载。")
            if not self._processes:
                self._release_requested.clear()

    async def resolve(self, task: str, language: str) -> LocalSpeechProfile:
        registered = self._registered.get((task, language))
        if registered is not None:
            return registered
        settings = load_compute(self.store.root)
        choice = read_json(self.store.root / "selections.json", {}).get(
            f"{language}:conversation:{task}", {}
        )
        package = self.catalog.get(choice.get("id"))
        if not choice:
            raise ValueError("speech_model_not_selected")
        if (
            not package
            or choice.get("fingerprint") != package.fingerprint
            or language not in package.available_languages
            or not self.store.installed(package)
            or choice.get("adapter_revision", 1) != adapter_revision(package.adapter)
        ):
            raise ValueError("speech_model_selection_stale")
        old = self._specs.get(task)
        occupied = sum(
            self._vram(s)
            for key, s in list(self._specs.items())
            if key != task and s["provider"] == "cuda"
        )
        hardware = await asyncio.to_thread(detect_hardware, self.store.root)
        # A resident model already accounts for its memory in nvidia-smi's free value.
        if old and old["id"] == package.id and old["provider"] == "cuda":
            gpus = hardware.get("gpus", [])
            if settings.gpu_index < len(gpus):
                gpus[settings.gpu_index]["available_mb"] += device_profile(package)["vram_mb"]
        device, reason = resolve_device(package, settings, hardware, occupied_mb=occupied)
        from .installation import managed_status, runtime_id_for
        native = package.adapter in {"voicevox", "melo_english"}
        status = managed_status(self.store.root, runtime_id_for(package, device)) if native else runtime_status(self.store.root, device)
        python = status.get("python") if native else runtime_python(self.store.root, device)
        if not status.get("prepared"):
            # Auto may use CPU only if there is a prepared CPU runtime; expose the reason.
            if (
                device == "cuda"
                and getattr(settings, f"{task}_device") == "auto"
                and (managed_status(self.store.root, runtime_id_for(package, "cpu")) if native else runtime_status(self.store.root, "cpu")).get("prepared")
            ):
                device, python, reason = (
                    "cpu",
                    runtime_python(self.store.root, "cpu"),
                    "GPU 运行环境未准备，当前使用 CPU。",
                )
            else:
                raise ValueError("speech_runtime_not_ready")
        report_args = {"voice_id": choice.get("voice_id")} if native else {}
        reports = matching_reports(
            self.store, package, language, hardware, device, settings.gpu_index, **report_args
        )
        if not reports:
            raise ValueError("speech_model_benchmark_required")
        if task == "stt":
            rows = reports[0].get("metrics", {}).get("sequential", {}).get(task, [])
            values = [
                r.get("finalization_compute_ms", r.get("compute_ms", float("inf")))
                for r in rows
            ]
            if (
                not values
                or sum(values) / len(values) > 500
                or not all(r.get("nonempty") for r in rows)
            ):
                raise ValueError("speech_model_too_slow")
        from .model_profile import build_profile
        from .model_profile import voices
        selected_voice = next((v for v in voices(package.id) if v["id"] == choice.get("voice_id")), None)
        return build_profile(self.store, package, language, device, gpu_index=settings.gpu_index,
                             vram_budget_mb=max(512, settings.vram_budget_mb - occupied),
                             idle_seconds=settings.idle_seconds, reason=reason,
                             python_override=python if not native else None, voice=selected_voice)

    async def execute(
        self, profile: LocalSpeechProfile, *, audio: bytes | None = None, text: str | None = None
    ) -> dict:
        """Execute a frozen binding without consulting mutable model selections."""
        if profile.task == "stt" and audio is not None and text is None:
            if len(audio) > 24 * 1024**2:
                raise ValueError("speech_audio_too_large")
            payload = {"audio": base64.b64encode(audio).decode("ascii")}
        elif profile.task == "tts" and text is not None and audio is None:
            payload = {"text": text}
        else:
            raise ValueError("speech_request_task_mismatch")
        return await self._request(profile.task, profile.language, _profile=profile, **payload)

    async def verify(self, profile: LocalSpeechProfile) -> None:
        """Check actual inference once per resident process and frozen profile."""
        from lingualoop.core.voice import SpeechSegment
        from .samples import benchmark_audio

        identity = (profile.model_json, self.worker_pid(profile.task))
        if identity[1] is not None and self._verified.get(profile.task) == identity:
            return
        if profile.task == "stt":
            with benchmark_audio(profile.language) as sample:
                result = await self.execute(profile, audio=sample.read_bytes())
            text = result.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("speech_model_verification_failed")
        else:
            text = {
                "en": "This is a voice check.",
                "ja": "音声の準備を確認します。",
                "zh": "语音准备检查。",
            }.get(profile.language, "Voice check.")
            result = await self.execute(profile, text=text)
            try:
                audio = base64.b64decode(result["audio"], validate=True)
                SpeechSegment.from_wav("preflight", 0, text, audio)
            except (KeyError, ValueError, TypeError) as error:
                raise ValueError("speech_model_verification_failed") from error
        pid = self.worker_pid(profile.task)
        if pid is not None:
            self._verified[profile.task] = (profile.model_json, pid)

    async def _request(self, task: str, language: str, *, _profile=None, **payload) -> dict:
        async with self._locks.setdefault(task, asyncio.Lock()):
            profile = _profile or await self.resolve(task, language)
            if profile.task != task or profile.language != language:
                raise ValueError("speech_profile_mismatch")
            spec, python, reason = profile.spec, profile.python, profile.reason
            spec["runtime_python"] = str(Path(python).resolve())
            package = self.catalog.get(profile.package_id)
            old = self._specs.get(task)
            if old is not None and instance_key(old) != instance_key(spec):
                await self._stop(task)
            async with self._admission_lock:
                if task not in self._processes or self._processes[task].returncode is not None:
                    await self._admit(task, spec)
                    await self._stop(task)
                    held = package_lock(self.store.root, package) if package else nullcontext()
                    held.__enter__()
                    self._package_locks[task] = held
                    try:
                        self._processes[task] = await asyncio.create_subprocess_exec(
                            python,
                            str(Path(__file__).with_name("inference_worker.py")),
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                            env=child_environment(),
                            limit=64 * 1024**2,
                            creationflags=subprocess_flags(),
                        )
                    except BaseException:
                        await self._stop(task)
                        raise
                    self._specs[task] = spec
            process = self._processes[task]
            self._specs[task] = spec
            if self._reaper is None:
                self._reaper = asyncio.create_task(self._idle())
            self._status(f"{task.upper()} · {profile.package_id} · {spec['provider'].upper()} · {reason}")
            try:
                process.stdin.write((json.dumps({"model": spec, **payload}) + "\n").encode())
                await process.stdin.drain()
                async with asyncio.timeout(120):
                    for _ in range(100):
                        raw = await process.stdout.readline()
                        if not raw:
                            raise RuntimeError("本地语音进程已退出，请检查可用内存和运行环境。")
                        if raw.startswith(b'{"worker_pid":'):
                            self._actual_pids[task] = int(json.loads(raw)["worker_pid"])
                            continue
                        if raw.startswith(b'{"ok":'):
                            response = json.loads(raw)
                            break
                    else:
                        raise RuntimeError("本地语音进程未返回有效结果。")
                if not response.get("ok"):
                    raise ValueError(response.get("error", "本地语音失败。"))
                self._last_used[task] = time.monotonic()
                result = response["result"]
                self.last_metrics[task] = {key: value for key, value in result.items()
                    if key not in {"text", "audio", "hypothesis"}}
                ms = result.get("first_pcm_ms", result.get("compute_ms", 0))
                self._status(
                    f"{task.upper()} · {spec['provider'].upper()} · 本轮计算 {ms:.0f} ms"
                    + (
                        f" · 首次加载 {result['load_ms']:.0f} ms"
                        if result["cold"]
                        else " · 模型已驻留"
                    )
                )
                return result
            except BaseException:
                await self._stop(task)
                raise
            finally:
                if profile.idle_seconds == 0:
                    await self._stop(task)

    async def transcribe(self, audio: bytes, language: str) -> str:
        if len(audio) > 24 * 1024**2:
            raise ValueError("录音过大。")
        result = await self._request("stt", language, audio=base64.b64encode(audio).decode())
        return result["text"]

    async def synthesize(self, text: str, language: str) -> bytes:
        result = await self._request("tts", language, text=text)
        return base64.b64decode(result["audio"], validate=True)


def subprocess_flags() -> int:
    import subprocess

    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
