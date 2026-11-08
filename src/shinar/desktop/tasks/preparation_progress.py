"""Shared preparation labels; independent of the download list model."""

import httpx
from PySide6.QtCore import QCoreApplication
from shinar.local_speech.downloads import DownloadCancelled


def preparation_phase_text(phase: str) -> str:
    messages = {
        "speech_setup_bootstrap": QCoreApplication.translate(
            "Desktop", "准备独立 Python 与安装工具"
        ),
        "speech_setup_resources": QCoreApplication.translate("Desktop", "准备词典与共享资源"),
        "speech_setup_wheels": QCoreApplication.translate("Desktop", "准备运行库"),
        "speech_setup_installing": QCoreApplication.translate("Desktop", "离线安装运行库"),
        "speech_setup_probing": QCoreApplication.translate("Desktop", "执行计算验证"),
        "speech_setup_vad": QCoreApplication.translate("Desktop", "准备人声检测组件 Silero VAD"),
        "speech_setup_server": QCoreApplication.translate(
            "Desktop", "准备本机语音连接组件 LiveKit"
        ),
        "speech_setup_model": QCoreApplication.translate("Desktop", "准备模型文件"),
        "speech_setup_waiting": QCoreApplication.translate("Desktop", "等待共享运行环境"),
        "downloading": QCoreApplication.translate("Desktop", "下载"),
        "verifying": QCoreApplication.translate("Desktop", "校验文件"),
        "extracting": QCoreApplication.translate("Desktop", "解包文件"),
        "waiting": QCoreApplication.translate("Desktop", "等待共享组件，其他任务继续"),
    }
    return messages.get(phase, messages["speech_setup_model"])


def preparation_transfer_text(done: int, total: int) -> str:
    if not total:
        return ""
    divisor = 1024**2 if total >= 1024**2 else 1024
    template = (
        QCoreApplication.translate("Desktop", "%1 / %2 MiB")
        if divisor == 1024**2
        else QCoreApplication.translate("Desktop", "%1 / %2 KiB")
    )
    return template.replace("%1", f"{done / divisor:.1f}").replace("%2", f"{total / divisor:.1f}")


def preparation_error(error: Exception) -> str:
    """Keep arbitrary HTTP bodies, URLs and machine paths out of the interface."""
    import re

    code = str(error)
    if isinstance(error, DownloadCancelled):
        return "speech_setup_cancelled"
    if isinstance(error, httpx.TransportError):
        return "speech_download_interrupted"
    if isinstance(error, httpx.HTTPStatusError):
        return "speech_download_source_unavailable"
    if isinstance(error, OSError) and getattr(error, "errno", None) == 28:
        return "speech_setup_disk_insufficient"
    return code if re.fullmatch(r"speech_[a-z_]+", code) else "speech_setup_failed"


def preparation_error_text(code: str) -> str:
    messages = {
        "speech_setup_cancelled": QCoreApplication.translate(
            "Desktop", "已取消，已下载部分保留，可继续。"
        ),
        "speech_download_interrupted": QCoreApplication.translate(
            "Desktop", "下载连接中断，重试会继续已下载部分。"
        ),
        "speech_download_source_unavailable": QCoreApplication.translate(
            "Desktop", "下载源暂不可用，请稍后重试。"
        ),
        "speech_setup_disk_insufficient": QCoreApplication.translate(
            "Desktop", "缓存盘空间不足，请释放空间后重试。"
        ),
        "speech_voice_terms_required": QCoreApplication.translate(
            "Desktop", "请先展开详情，阅读并确认语音模型与角色条款。"
        ),
        "speech_device_unsupported": QCoreApplication.translate(
            "Desktop", "当前设备不支持此模型，请选择自动或 CPU。"
        ),
        "speech_runtime_probe_failed": QCoreApplication.translate(
            "Desktop", "运行环境未通过计算验证，请检查驱动或重试。"
        ),
    }
    return messages.get(
        code,
        QCoreApplication.translate("Desktop", "准备未完成，请检查网络、磁盘与运行环境后重试。"),
    )
