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
            RowLayout {
                Layout.fillWidth: true
                MLabel { text: qsTr("计算设备"); role: "label" }
                MHelpButton { objectName: "speechDeviceHelp"; helpText: qsTr("自动模式按模型和可用显存选择 GPU 或 CPU；手动选 GPU 时失败会直接报告。关闭本地识别或合成后使用已配置的远程服务。本地模型按语言和用途选用。") }
            }
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
        }
        MCard {
            color: "transparent"; padding: 0
            RowLayout {
                Layout.fillWidth: true
                MLabel { text: qsTr("显存与模型驻留"); role: "label" }
                MHelpButton { objectName: "speechResidencyHelp"; helpText: qsTr("显存预算用于加载前检查和 CUDA 内存池配置，不是进程显存硬上限；驱动和运行库还会额外占用。降低预算可能改用 CPU 或需要更小的模型。释放模型会增加下次加载的等待时间。") }
            }
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
        }
        MCard {
            color: "transparent"; padding: 0
            RowLayout {
                Layout.fillWidth: true
                MLabel { text: qsTr("当前资源"); role: "label" }
                MHelpButton { objectName: "speechResourceHelp"; helpText: qsTr("每 2 秒采样。整卡使用率包含其他应用；Windows 驱动可能不提供进程显存读数。监测不会加载尚未使用的模型。") }
            }
            MLabel { text: speechLibrary.hardwareSummary; role: "supporting" }
            MLabel { objectName: "speechResourceSummary"; text: speechLibrary.resourceSummary; role: "label" }
        }
        MCard {
            color: "transparent"; padding: 0
            RowLayout {
                Layout.fillWidth: true
                MLabel { text: qsTr("运行环境"); role: "label" }
                MHelpButton { objectName: "speechRuntimeHelp"; helpText: qsTr("NVIDIA GPU 需要合适的显卡驱动，驱动变化后请重新检查。软件按需准备 CUDA / cuDNN 运行库，通常无需完整 CUDA Toolkit。安装预留空间包含临时文件，实际占用见空间说明。") }
            }
            Repeater {
                model: ["cpu", "cuda", "voicevox-cpu", "melo-cpu", "melo-cuda"]
                ColumnLayout {
                    required property string modelData
                    Layout.fillWidth: true
                    MLabel { text: ({cpu: qsTr("ONNX CPU"), cuda: qsTr("ONNX NVIDIA GPU"), "voicevox-cpu": qsTr("VOICEVOX CPU"), "melo-cpu": qsTr("Melo 英文 CPU"), "melo-cuda": qsTr("Melo 英文 NVIDIA GPU")})[modelData] + " · " + (speechLibrary.runtimes[modelData].prepared ? qsTr("已验证") : qsTr("未准备或未验证")); role: "label" }
                    SpeechPreparationSize { visible: !speechLibrary.runtimes[modelData].prepared; explain: true; downloadMiB: speechLibrary.runtimes[modelData].downloadMiB; requiredFreeMiB: speechLibrary.runtimes[modelData].diskMiB }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        MButton { objectName: "prepareRuntime-" + modelData; text: qsTr("准备 / 修复"); enabled: !speechLibrary.busy; onClicked: speechLibrary.prepareRuntime(modelData) }
                        MButton { objectName: "checkRuntime-" + modelData; text: qsTr("重新检查"); variant: "outlined"; enabled: !speechLibrary.busy; onClicked: speechLibrary.checkRuntime(modelData) }
                    }
                }
            }
        }
        MLabel { objectName: "computeStatus"; visible: text.length > 0; text: speechLibrary.status; Accessible.role: Accessible.AlertMessage }
        ProgressBar { Layout.fillWidth: true; visible: speechLibrary.busy; indeterminate: true }
        MButton { text: qsTr("取消当前任务"); variant: "outlined"; visible: speechLibrary.busy; onClicked: speechLibrary.cancel() }
        Item { Layout.preferredHeight: 16 }
    }
}
