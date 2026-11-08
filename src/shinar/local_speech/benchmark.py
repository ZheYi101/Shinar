from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from . import RUNTIME_VERSION, adapter_revision
from .downloads import DownloadCancelled, ModelStore, package_lock
from .hardware import admission, detect_hardware
from .storage import atomic_json
from .processes import terminate_tree

from shinar.configuration import getenv


def percentile(values, q=0.95):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * q) - 1)] if ordered else None


def summarize(result):
    output = {}
    for mode in ("sequential", "concurrent"):
        for task, rows in result[mode].items():
            if not rows:
                continue
            for key in ("compute_ms", "finalization_compute_ms", "first_pcm_ms", "rtf"):
                values = [r[key] for r in rows if key in r]
                if values:
                    output[f"{mode}_{task}_{key}_p50"] = percentile(values, 0.5)
                    output[f"{mode}_{task}_{key}_p95"] = percentile(values)
    return output


def benchmark(
    store: ModelStore,
    packages,
    language,
    *,
    wav=None,
    repeats=5,
    threads=2,
    cancel=None,
    timeout=180,
    python=None,
    devices=None,
    gpu_index=0,
    vram_budget_mb=3072,
    profiles=None,
):
    if not packages or len(packages) > 2 or len({p.task for p in packages}) != len(packages):
        raise ValueError("测速需要一个模型，或一组 STT + TTS。")
    if not 3 <= repeats <= 20 or not 1 <= threads <= 4:
        raise ValueError("测速次数为 3–20；每模型线程数为 1–4。")
    if any(language not in p.available_languages for p in packages):
        raise ValueError("模型不支持所选语言。")
    devices = devices or {p.id: "cpu" for p in packages}
    if any(devices.get(p.id) not in {"cpu", "cuda"} for p in packages):
        raise ValueError("未知计算设备。")
    hardware = detect_hardware(store.root)
    for package in packages:
        permitted, reason = admission(package, hardware)
        if not permitted:
            raise ValueError(reason)
    budget = sum(p.evaluation_budget_mb for p in packages) + 2048
    if hardware["available_ram_bytes"] < budget * 1024**2:
        raise ValueError("当前可用内存不足以同时测试这组模型。")
    if any(p.task == "stt" for p in packages) and not wav:
        raise ValueError("请选择自己有权使用的 16kHz 单声道 PCM WAV（最多 60 秒）。")
    if profiles and len({p.python for p in profiles.values()}) > 1:
        from .paired_benchmark import benchmark_profiles
        return benchmark_profiles(store, packages, language, profiles, wav=wav, repeats=repeats,
                                  threads=threads, cancel=cancel, timeout=timeout, hardware=hardware)
    with ExitStack() as stack:
        for package in sorted(packages, key=lambda p: p.id):
            stack.enter_context(package_lock(store.root, package))
            if not store.installed(package):
                raise ValueError("请先下载并校验模型。")
        report_id = "--".join(sorted(p.id for p in packages)) + "--" + language
        report_id += "--" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        report_dir = store.root / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        preview = (
            report_dir / (report_id + ".wav") if any(p.task == "tts" for p in packages) else None
        )
        request = {
            "models": [
                {
                    "id": p.id,
                    "task": p.task,
                    "path": str(store.model_path(p)),
                    "adapter": p.adapter,
                    "language": language,
                    "provider": devices[p.id],
                    "gpu_index": gpu_index,
                    "vram_budget_mb": vram_budget_mb,
                }
                for p in packages
            ],
            "wav": str(Path(wav).absolute()) if wav else None,
            "repeats": repeats,
            "threads": threads,
            "preview": str(preview) if preview else None,
            "runtime_version": RUNTIME_VERSION,
        }
        if profiles:
            request["models"] = [profiles[p.id].spec for p in packages]
            python = next(iter(profiles.values())).python
        result = _run_benchmark_process(request, python, threads, cancel, timeout)
        report = {
            "schema": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_fingerprints": {p.id: p.fingerprint for p in packages},
            "adapter_revisions": {p.id: adapter_revision(p.adapter) for p in packages},
            "language": language,
            "hardware": hardware,
            "metrics": result,
            "summary": summarize(result),
            "repeats": repeats,
            "preview": str(preview) if preview else None,
            "accuracy_evaluated": False,
            "live_chain_evaluated": False,
        }
        from .model_profile import measurement_identity
        report["model_identities"] = {
            p.id: measurement_identity(
                store.root, p, devices[p.id],
                profiles[p.id].spec.get("voice_id") if profiles else None,
            ) for p in packages
        }
        atomic_json(report_dir / (report_id + ".json"), report)
        return report


def _run_benchmark_process(request, python, threads, cancel, timeout):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    # Keep source-checkout support, without exposing credentials to the child.
    env = {
        k: v
        for k, v in env.items()
        if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    env["OMP_NUM_THREADS"] = str(threads)
    env.pop("PYTHONPATH", None)
    command = [
        python or getenv("SHINAR_SPEECH_PYTHON") or sys.executable,
        str(Path(__file__).with_name("runtime_worker.py")),
    ]
    # Redirect native stderr to an ephemeral file so verbose native logs cannot
    # fill a pipe and deadlock. Do not persist raw logs or input audio.
    import tempfile

    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
            process.stdin.close()
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel and cancel.wait(0.05):
                    raise DownloadCancelled("测速已取消。")
                if not cancel:
                    time.sleep(0.05)
                if time.monotonic() > deadline:
                    raise RuntimeError("测速超时，已释放模型进程。")
            stdout.seek(0)
            lines = stdout.read(2 * 1024**2).decode("utf-8", errors="replace").splitlines()
            payload = next(
                (json.loads(line) for line in reversed(lines) if line.startswith('{"ok":')),
                None,
            )
            if not payload or not payload.get("ok"):
                raise RuntimeError(
                    payload.get("error")
                    if payload
                    else "本地运行环境不可用，请安装 local-speech extra 或配置独立 Python。"
                )
            result = payload["result"]
            return result
        finally:
            if process.poll() is None:
                terminate_tree(process.pid)
                process.wait(timeout=5)
