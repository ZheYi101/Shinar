"""Optional isolated runtimes; no global Python, CUDA, drivers or PATH changes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .downloads import DownloadCancelled
from .storage import atomic_json, read_json
from .processes import terminate_tree
from shinar.configuration import canonical_environment


def runtime_python(root: Path, device: str) -> str:
    from .installation import managed_status
    current = managed_status(root, "ort-" + device)
    if current.get("prepared"):
        return current["python"]
    folder = root / "runtimes" / ("cuda12-ort1232-v1" if device == "cuda" else "cpu-v1")
    python = folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(python)


def child_environment() -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
    }
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env.update(
        PYTHONUTF8="1",
        PYTHONNOUSERSITE="1",
        OMP_NUM_THREADS="2",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return canonical_environment(env)


def run_bounded(command: list[str], *, cancel=None, timeout=60) -> str:
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            command,
            stdout=output,
            stderr=output,
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if cancel and cancel.wait(0.1):
                    raise DownloadCancelled("运行环境准备已取消；可重试。")
                if not cancel:
                    time.sleep(0.1)
                if time.monotonic() > deadline:
                    raise RuntimeError("运行环境操作超时，请重试。")
            if process.returncode:
                raise RuntimeError("运行环境未就绪：请检查网络、Python 版本和显卡驱动后重试。")
            output.seek(0)
            return output.read(2 * 1024**2).decode("utf-8", errors="replace")
        finally:
            if process.poll() is None:
                terminate_tree(process.pid)
                process.wait(timeout=5)


def probe_runtime(python: str, device: str, *, gpu_index=0, cancel=None) -> dict:
    raw = run_bounded(
        [python, str(Path(__file__).with_name("runtime_probe.py")), device, str(gpu_index)],
        cancel=cancel,
    )
    try:
        value = json.loads(raw.strip().splitlines()[-1])
        if not value["ok"] or value["device"] != device:
            raise ValueError
        return value
    except (ValueError, KeyError, IndexError):
        raise RuntimeError("运行环境探测失败，GPU 没有通过实际计算验证。") from None


def install_runtime(root: Path, device: str, *, cancel=None, gpu_index=0) -> dict:
    if os.name == "nt":
        from .installation import prepare_managed_runtime
        return prepare_managed_runtime(root, "ort-" + device, cancel=cancel, gpu_index=gpu_index, repair=True)
    if device not in {"cpu", "cuda"}:
        raise ValueError("未知运行环境。")
    if sys.version_info[:2] not in {(3, 11), (3, 12), (3, 13)} or getattr(sys, "frozen", False):
        raise ValueError("自动准备运行环境目前需要 Python 3.11–3.13 版桌面程序。")
    python = runtime_python(root, device)
    folder = Path(python).parent.parent
    folder.parent.mkdir(parents=True, exist_ok=True)
    marker = folder / "ready.json"
    marker.unlink(missing_ok=True)
    if not Path(python).is_file():
        run_bounded([sys.executable, "-m", "venv", str(folder)], cancel=cancel, timeout=120)
    requirements = [
        "sherpa-onnx==1.13.8",
        "sherpa-onnx-core==1.13.8",
        "numpy==2.4.6",
        "psutil==7.2.2",
        "kaldi-native-fbank==1.22.3",
        "onnx==1.19.1",
    ]
    requirements += (
        ["onnxruntime-gpu[cuda,cudnn]==1.23.2"] if device == "cuda" else ["onnxruntime==1.23.2"]
    )
    if device == "cuda":
        requirements += [
            "nvidia-cuda-nvrtc-cu12==12.8.93",
            "nvidia-cuda-runtime-cu12==12.8.90",
            "nvidia-cufft-cu12==11.3.3.83",
            "nvidia-curand-cu12==10.3.9.90",
            "nvidia-cublas-cu12==12.8.4.1",
            "nvidia-cudnn-cu12==9.10.2.21",
            "nvidia-nvjitlink-cu12==12.8.93",
        ]
    # Explicit index prevents a personal extra-index or pip config from redirecting installs.
    run_bounded(
        [
            python,
            "-m",
            "pip",
            "--isolated",
            "install",
            "--index-url",
            "https://pypi.org/simple",
            "--only-binary=:all:",
            *requirements,
        ],
        cancel=cancel,
        timeout=1800,
    )
    result = probe_runtime(python, device, gpu_index=gpu_index, cancel=cancel)
    atomic_json(marker, result)
    return result


def runtime_status(root: Path, device: str) -> dict:
    from .installation import managed_status
    current = managed_status(root, "ort-" + device)
    if current.get("prepared"):
        return current
    python = Path(runtime_python(root, device))
    marker = read_json(python.parent.parent / "ready.json", {})
    return {"prepared": python.is_file() and marker.get("ok") is True, **marker}
