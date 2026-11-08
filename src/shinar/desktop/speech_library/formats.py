"""Qt text formatting on the facade thread, with existing translation contexts."""

from PySide6.QtCore import QCoreApplication
from shinar.desktop.presentation.conversation_presentation import display_value


def catalog_display(result):
    value = display_value(result)
    for row in value["rows"]:
        if row["_adapter"] == "voicevox":
            row["notes"] = QCoreApplication.translate(
                "Desktop", "ずんだもん：本轮支持 CPU，需确认模型与角色条款并保留署名。"
            )
            row["deviceNote"] = QCoreApplication.translate(
                "Desktop", "本轮仅支持 CPU；尚未开放 GPU 加速。"
            )
        elif row["_adapter"] == "melo_english":
            row["notes"] = QCoreApplication.translate(
                "Desktop", "独立英文：CPU 可用但较慢，CUDA 已验证提速；采用整句合成。"
            )
            row["deviceNote"] = QCoreApplication.translate(
                "Desktop", "推荐使用已验证的 NVIDIA GPU；实际速度与资源需求以本机测速为准。"
            )
        if row["_adapter"] in {"voicevox", "melo_english"}:
            row["streaming"] = QCoreApplication.translate("Desktop", "按句合成，返回完整音频")
            stats = row["measurementStats"]
            row["measurement"] = QCoreApplication.translate("Desktop", "尚未本机测速")
            if stats:
                row["measurement"] = (
                    QCoreApplication.translate(
                        "Desktop", "%1 · 热态整句合成平均 %2 / p95 %3 ms · %4 次"
                    )
                    .replace("%1", row["device"].upper())
                    .replace("%2", f"{stats['average_ms']:.0f}")
                    .replace("%3", f"{stats['p95_ms']:.0f}")
                    .replace("%4", str(stats["repeats"]))
                )
                if stats["concurrent_p95_ms"] is not None:
                    row["measurement"] += QCoreApplication.translate(
                        "Desktop", "；并发整句合成 p95 %1 ms"
                    ).replace("%1", f"{stats['concurrent_p95_ms']:.0f}")
        row.pop("_adapter", None)
        if row.get("setupError") == "library_message_7":
            row["setupError"] = QCoreApplication.translate(
                "Desktop", "当前计算设备不支持此模型，请切换自动或 CPU。"
            )
    return value


def work_error(value):
    return {
        "library_network_error": QCoreApplication.translate(
            "Desktop", "下载连接中断，已下载部分保留，请重试继续。"
        ),
        "library_http_error": QCoreApplication.translate(
            "Desktop", "下载源暂不可用或拒绝请求，请稍后重试。"
        ),
        "library_unknown_error": QCoreApplication.translate(
            "Desktop", "操作未完成，请检查网络、磁盘与本地运行依赖后重试。"
        ),
        "library_message_0": QCoreApplication.translate(
            "Desktop", "请先停止语音并释放已加载模型，再修复运行环境。"
        ),
        "library_message_1": QCoreApplication.translate(
            "Desktop", "请先在计算与加速中准备对应运行环境。"
        ),
        "library_message_2": QCoreApplication.translate(
            "Desktop", "请先测速并保存本语言的 STT 与 TTS 候选。"
        ),
        "library_message_3": QCoreApplication.translate("Desktop", "模型已更新，请重新测速选择。"),
        "library_message_4": QCoreApplication.translate(
            "Desktop", "运行时已更新，请重新测速选择。"
        ),
        "library_message_5": QCoreApplication.translate(
            "Desktop", "模型加载配置已更新，请重新测速选择。"
        ),
        "library_message_6": QCoreApplication.translate(
            "Desktop", "请先准备所选计算设备的运行环境。"
        ),
        "library_message_7": QCoreApplication.translate(
            "Desktop", "当前计算设备不支持此模型，请切换自动或 CPU。"
        ),
    }.get(value, value)
