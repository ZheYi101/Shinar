"""Device policy shared by the library, benchmarks and live local inference."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from typing import Literal

from .storage import atomic_json, read_json
from .storage_lease import storage_lease


class ComputeSettings(BaseModel):
    stt_device: Literal["auto", "cpu", "cuda"] = "auto"
    tts_device: Literal["auto", "cpu", "cuda"] = "auto"
    gpu_index: int = Field(default=0, ge=0, le=15)
    vram_budget_mb: int = Field(default=3072, ge=512, le=65536)
    reserve_vram_mb: int = Field(default=1024, ge=256, le=32768)
    idle_seconds: int = Field(default=120, ge=0, le=3600)
    local_stt: bool = False
    local_tts: bool = False


def load_compute(root: Path) -> ComputeSettings:
    try:
        return ComputeSettings.model_validate(read_json(root / "compute.json", {}))
    except ValueError:
        return ComputeSettings()


def save_compute(root: Path, settings: ComputeSettings) -> None:
    with storage_lease(root):
        atomic_json(root / "compute.json", settings.model_dump())


def device_profile(package) -> dict:
    # These numbers are admission estimates, not promises or a hard process cap.
    # The speed preference comes from the fixed 2026-10-29 local evaluation.
    if package.adapter == "sensevoice-ort":
        return {
            "cuda": True,
            "prefer_gpu": True,
            "vram_mb": 1536,
            "note": "推荐 GPU：2024 FP32 实测约 53–58 ms；CPU 约 505–714 ms，未通过平均 500 ms 筛选。",
        }
    if package.adapter == "melo_english":
        return {"cuda": True, "prefer_gpu": True, "vram_mb": 1536,
                "note": "独立英文已验证 CUDA 提速；CPU 整句合成较慢，实际表现以本机测速为准。"}
    return {
        "cuda": False,
        "prefer_gpu": False,
        "vram_mb": 0,
        "note": "此适配器使用 CPU；轻量或 INT8 配置没有已验证的 GPU 提速收益。",
    }


def resolve_device(
    package, settings: ComputeSettings, hardware: dict, *, occupied_mb=0
) -> tuple[str, str]:
    profile = device_profile(package)
    choice = getattr(settings, f"{package.task}_device")
    if choice == "cpu":
        return "cpu", "手动选择 CPU"
    if not profile["cuda"]:
        if choice == "cuda":
            raise ValueError("此模型的 GPU 适配尚未验证，请选择自动或 CPU。")
        return "cpu", profile["note"]
    gpus = hardware.get("gpus", [])
    reason = "未检测到所选 NVIDIA GPU"
    if settings.gpu_index < len(gpus):
        gpu = gpus[settings.gpu_index]
        needed = profile["vram_mb"]
        if occupied_mb + needed > settings.vram_budget_mb:
            reason = "已加载模型加上此模型超出语音显存预算"
        elif gpu["available_mb"] < needed + settings.reserve_vram_mb:
            reason = "当前空闲显存不足，需为其他应用保留显存"
        else:
            return "cuda", profile["note"]
    if choice == "cuda":
        raise ValueError(reason + "；未自动改用 CPU。")
    return "cpu", reason + "；自动改用 CPU，需重新检查平均延迟是否达标。"


def runtime_version(package) -> str:
    if package.adapter == "voicevox":
        return "voicevox-0.17.1"
    if package.adapter == "melo_english":
        return "torch-2.9.1-transformers-4.57.3"
    return "1.23.2" if package.adapter == "sensevoice-ort" else "1.13.8"
