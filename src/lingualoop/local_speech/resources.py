"""Read-only GPU telemetry. Unsupported process accounting stays unknown."""

from __future__ import annotations

import os
import subprocess


def _query(arguments: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", *arguments, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


def resource_snapshot(pids: list[int], gpu_pids: list[int] | None = None) -> dict:
    gpu_pids = pids if gpu_pids is None else gpu_pids
    cards = []
    for line in _query(["--query-gpu=index,name,memory.total,memory.used,utilization.gpu"]):
        try:
            index, name, total, used, utilization = (p.strip() for p in line.split(","))
            cards.append(
                {
                    "index": int(index),
                    "name": name,
                    "total_mb": int(total),
                    "used_mb": int(used),
                    "utilization": float(utilization),
                }
            )
        except ValueError:
            continue
    process_mb = 0 if not gpu_pids else None
    found = {}
    for line in _query(["--query-compute-apps=pid,used_gpu_memory"]):
        try:
            pid, used = (p.strip() for p in line.split(","))
            if int(pid) in gpu_pids:
                found[int(pid)] = found.get(int(pid), 0) + int(used)
        except ValueError:
            continue
    if gpu_pids and all(pid in found for pid in gpu_pids):
        process_mb = sum(found.values())
    return {"gpus": cards, "speech_process_mb": process_mb, "process_count": len(pids)}
