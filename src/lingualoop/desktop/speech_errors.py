"""Translate safe speech error codes with the affected language and task."""

import re
from PySide6.QtCore import QCoreApplication


def safe_speech_code(error: Exception) -> str:
    code = str(error)
    return code if re.fullmatch(r"speech_[a-z_]+", code) else "speech_service_failed"


def speech_error_text(code: str, task: str, language: str) -> str:
    languages = {
        "en": QCoreApplication.translate("Desktop", "英语"),
        "ja": QCoreApplication.translate("Desktop", "日语"),
        "zh": QCoreApplication.translate("Desktop", "中文"),
        "ko": QCoreApplication.translate("Desktop", "韩语"),
        "fr": QCoreApplication.translate("Desktop", "法语"),
        "de": QCoreApplication.translate("Desktop", "德语"),
        "es": QCoreApplication.translate("Desktop", "西班牙语"),
    }
    kind = (
        QCoreApplication.translate("Desktop", "语音识别（STT）")
        if task == "stt"
        else QCoreApplication.translate("Desktop", "朗读（TTS）")
    )
    name = languages.get(language, language)
    if code in {
        "speech_model_not_selected",
        "speech_model_selection_stale",
        "speech_model_files_missing",
    }:
        return (
            QCoreApplication.translate(
                "Desktop",
                "尚未为%1选用可用的%2模型。请在本地语音模型中准备、测速并选用；其他语言的选择不能用于本会话。",
            )
            .replace("%1", name)
            .replace("%2", kind)
        )
    if code == "speech_model_benchmark_required":
        return (
            QCoreApplication.translate(
                "Desktop", "%1的%2模型尚未完成当前设备的测速，请在本地语音模型中测速并重新选用。"
            )
            .replace("%1", name)
            .replace("%2", kind)
        )
    if code == "speech_model_verification_failed":
        return (
            QCoreApplication.translate(
                "Desktop", "%1的%2模型自检未通过，请检查模型与运行环境后重试；检查内容未发送到学习对话。"
            )
            .replace("%1", name)
            .replace("%2", kind)
        )
    if code == "speech_runtime_not_ready":
        return (
            QCoreApplication.translate(
                "Desktop", "%1的%2运行环境未准备，请在本地语音模型中继续准备。"
            )
            .replace("%1", name)
            .replace("%2", kind)
        )
    if code == "speech_ram_budget_exceeded":
        return QCoreApplication.translate(
            "Desktop", "可用内存不足以加载所选语音模型，请释放内存或选择更小的模型。"
        )
    if code in {"speech_vram_budget_exceeded", "speech_model_too_slow"}:
        return QCoreApplication.translate(
            "Desktop", "所选语音模型未通过当前设备的资源或速度要求，请检查计算与加速设置。"
        )
    if code == "speech_service_unavailable":
        return (
            QCoreApplication.translate(
                "Desktop", "%1未配置可用的%2服务，请在设置中选用本地模型或配置远程服务。"
            )
            .replace("%1", name)
            .replace("%2", kind)
        )
    return (
        QCoreApplication.translate(
            "Desktop", "%1的%2未完成，请检查模型、运行环境或服务连接后重试；文字对话仍可使用。"
        )
        .replace("%1", name)
        .replace("%2", kind)
    )
