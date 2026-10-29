import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ScrollView {
    id: page
    objectName: "speechComputePage"
    clip: true
    contentWidth: availableWidth
    onVisibleChanged: {
        speechLibrary.setResourceMonitoring(visible)
        if (visible && !speechLibrary.busy) speechLibrary.refresh()
    }
    ColumnLayout {
        width: Math.min(page.availableWidth,944); x: (page.availableWidth-width)/2
        spacing: AppTheme.gapLarge
        MCard {
            color: "transparent"; padding: 0
            MLabel { text: qsTr("计算设备"); role: "title" }
            MLabel { text: qsTr("自动模式对已验证提速明显的模型优先使用 GPU。硬件或空闲显存不足时考虑 CPU，并显示原因；手动选 GPU 时失败会直接报告。"); role: "supporting" }
            Repeater {
                model: [{key: "stt_device", title: qsTr("语音识别 STT")}, {key: "tts_device", title: qsTr("语音合成 TTS")}]
                ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    MLabel { text: modelData.title; role: "label" }
                    MComboBox {
                        objectName: "compute-" + modelData.key
                        Layout.fillWidth: true
                        model: [qsTr("自动（推荐）"), "CPU", "NVIDIA GPU（CUDA）"]
                        property var values: ["auto", "cpu", "cuda"]
                        currentIndex: values.indexOf(speechLibrary.compute[modelData.key])
                        enabled: !speechLibrary.busy
                        Accessible.name: qsTr("%1 计算设备").arg(modelData.title)
                        onActivated: speechLibrary.setCompute(modelData.key, values[currentIndex])
                    }
                }
            }
            MLabel { text: qsTr("GPU 编号（多显卡时选择）"); role: "label" }
            MSpinBox { objectName: "speechGpuIndex"; from: 0; to: 15; value: speechLibrary.compute.gpu_index; enabled: !speechLibrary.busy; onValueModified: speechLibrary.setCompute("gpu_index", value) }
            MSwitch { objectName: "localSttEnabled"; text: qsTr("使用本地识别"); checked: speechLibrary.compute.local_stt; enabled: !speechLibrary.busy; onToggled: speechLibrary.setCompute("local_stt", checked) }
            MSwitch { objectName: "localTtsEnabled"; text: qsTr("使用本地合成"); checked: speechLibrary.compute.local_tts; enabled: !speechLibrary.busy; onToggled: speechLibrary.setCompute("local_tts", checked) }
            MLabel { text: qsTr("关闭本地服务后使用已配置的远程连接。请先在语音模型中为对话语言选择模型。"); role: "supporting" }
        }
        MCard {
            color: "transparent"; padding: 0
            MLabel { text: qsTr("显存与模型驻留"); role: "title" }
            MLabel { text: qsTr("语音显存预算（MiB）"); role: "label" }
            MSpinBox { objectName: "speechVramBudget"; from: 512; to: 65536; stepSize: 256; editable: true; value: speechLibrary.compute.vram_budget_mb; enabled: !speechLibrary.busy; onValueModified: speechLibrary.setCompute("vram_budget_mb", value) }
            MLabel { text: qsTr("为其他应用保留的空闲显存（MiB）"); role: "label" }
            MSpinBox { objectName: "speechVramReserve"; from: 256; to: 32768; stepSize: 256; editable: true; value: speechLibrary.compute.reserve_vram_mb; enabled: !speechLibrary.busy; onValueModified: speechLibrary.setCompute("reserve_vram_mb", value) }
            MLabel { text: qsTr("空闲后释放"); role: "label" }
            MComboBox {
                objectName: "speechIdleRelease"
                Layout.fillWidth: true
                model: [qsTr("每次用完立即释放（下次需重新加载）"), qsTr("30 秒"), qsTr("2 分钟（推荐）"), qsTr("5 分钟"), qsTr("10 分钟")]
                property var values: [0, 30, 120, 300, 600]
                currentIndex: values.indexOf(speechLibrary.compute.idle_seconds)
                enabled: !speechLibrary.busy
                onActivated: speechLibrary.setCompute("idle_seconds", values[currentIndex])
            }
            MButton { objectName: "speechReleaseModels"; text: qsTr("释放已加载模型"); variant: "outlined"; onClicked: speechLibrary.releaseModels() }
            MLabel { text: qsTr("显存预算用于加载前准入与 CUDA 内存池配置，驱动、上下文和库还会额外占用；并非整个进程的硬上限。降低预算可能触发 CPU 或要求更换模型。空闲释放会增加下一次首字等待。"); role: "supporting" }
        }
        MCard {
            color: "transparent"; padding: 0
            MLabel { text: qsTr("当前资源"); role: "title" }
            MLabel { text: speechLibrary.hardwareSummary; role: "supporting" }
            MLabel { objectName: "speechResourceSummary"; text: speechLibrary.resourceSummary; role: "label" }
            MLabel { text: qsTr("每 2 秒采样。整卡使用率含其他应用，不等于本软件占用；Windows 驱动可能不提供进程显存读数。没有推理时不为监测而加载模型。"); role: "supporting" }
        }
        MCard {
            color: "transparent"; padding: 0
            MLabel { text: qsTr("运行环境"); role: "title" }
            MLabel { text: qsTr("NVIDIA GPU 需要合适的显卡驱动。软件按需下载匹配的 CUDA 12 / cuDNN 运行库到独立目录，通常无需安装完整 CUDA Toolkit；GPU 环境约需 1–2 GiB 下载和更多磁盘空间。"); role: "supporting" }
            Repeater {
                model: ["cpu", "cuda"]
                ColumnLayout {
                    required property string modelData
                    Layout.fillWidth: true
                    MLabel { text: (modelData === "cuda" ? "GPU" : "CPU") + " · " + (speechLibrary.runtimes[modelData].prepared ? qsTr("已通过计算探针（驱动变化后请重检）") : qsTr("尚未准备或验证")); role: "label" }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        MButton { objectName: "prepareRuntime-" + modelData; text: qsTr("准备 / 修复"); enabled: !speechLibrary.busy; onClicked: speechLibrary.prepareRuntime(modelData) }
                        MButton { objectName: "checkRuntime-" + modelData; text: qsTr("重新检查"); variant: "outlined"; enabled: !speechLibrary.busy; onClicked: speechLibrary.checkRuntime(modelData) }
                    }
                }
            }
        }
        MLabel { objectName: "computeStatus"; text: speechLibrary.status; Accessible.role: Accessible.AlertMessage }
        ProgressBar { Layout.fillWidth: true; visible: speechLibrary.busy; indeterminate: true }
        MButton { text: qsTr("取消当前任务"); variant: "outlined"; visible: speechLibrary.busy; onClicked: speechLibrary.cancel() }
        Item { Layout.preferredHeight: 16 }
    }
}
