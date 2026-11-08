from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


def detect_hardware(cache_root: Path) -> dict:
    """No unique hardware identifiers; GPU discovery is not runtime validation."""
    memory = available = None
    try:
        import psutil

        vm = psutil.virtual_memory()
        memory, available = vm.total, vm.available
    except ImportError:
        if os.name == "nt":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong)
                    for name in (
                        "total",
                        "available",
                        "total_page",
                        "available_page",
                        "total_virtual",
                        "available_virtual",
                        "extended",
                    )
                ]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory, available = status.total, status.available
        elif Path("/proc/meminfo").exists():
            values = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in Path("/proc/meminfo").read_text().splitlines()
                if len(line.split()) >= 2
            }
            memory, available = values.get("MemTotal"), values.get("MemAvailable")
    gpu = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                name, total, free = line.rsplit(",", 2)
                gpu.append(
                    {
                        "name": name.strip(),
                        "total_mb": int(total),
                        "available_mb": int(free),
                        "backend_verified": False,
                    }
                )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    existing = cache_root.absolute()
    while not existing.exists():
        existing = existing.parent
    cpu = platform.processor()
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "cpu": platform.processor(),
        "cpu_name": cpu,
        "logical_cpus": os.cpu_count() or 1,
        "ram_bytes": memory,
        "available_ram_bytes": available,
        "disk_free_bytes": shutil.disk_usage(existing).free,
        "gpus": gpu,
    }


def admission(package, hardware: dict) -> tuple[bool, str]:
    if not package.files:
        return False, "候选待适配：尚未开放下载"
    if hardware["architecture"].lower() not in {"amd64", "x86_64", "aarch64", "arm64"}:
        return False, "当前 CPU 架构尚未验证"
    available = hardware.get("available_ram_bytes")
    # Reserve 2 GiB for GUI/OS/other apps, in addition to the evaluation process.
    if available is None:
        return False, "无法读取可用内存，请通过 CLI 检查后再测速"
    if available < (package.evaluation_budget_mb + 2048) * 1024**2:
        return False, "当前可用内存不足以安全测速（含 2 GiB 余量）"
    required = sum(f.size + f.unpacked_limit for f in package.files) + 256 * 1024**2
    if hardware["disk_free_bytes"] < required:
        return False, "缓存盘剩余空间不足"
    return True, "可下载测速；是否适合实时对话以实测为准"
