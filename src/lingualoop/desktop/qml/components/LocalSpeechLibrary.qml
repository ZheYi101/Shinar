import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../design"

ScrollView {
    id: dialog
    objectName: "speechModelsPage"
    clip: true
    contentWidth: availableWidth
    signal openCompute()
    onVisibleChanged: {
        if (visible && !speechLibrary.busy) speechLibrary.refresh()
        else if (!visible) speechLibrary.stopPreview()
    }
    property string pendingModel: ""
    property string uninstallModel: ""
    property bool pairBenchmark: false

    FileDialog {
        id: audioFile
        title: "选择本地测速录音（16kHz、单声道、16-bit PCM、最多 60 秒）"
        nameFilters: ["PCM WAV (*.wav)"]
        onAccepted: {
            if (dialog.pairBenchmark) speechLibrary.runPairBenchmark(selectedFile.toString())
            else speechLibrary.runBenchmark(dialog.pendingModel, selectedFile.toString())
        }
    }
    MDialog {
        id: removeDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: "卸载所选语音模型？"
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: MLabel { text: "会删除这个模型包、下载缓存及候选选择。学习材料和对话历史保留。"; width: 240 }
        onAccepted: speechLibrary.uninstall(dialog.uninstallModel)
    }
    ColumnLayout {
        width: dialog.availableWidth
        spacing: AppTheme.gapLarge
        MButton { text: "计算设备与资源占用"; variant: "outlined"; onClicked: dialog.openCompute() }
        MLabel { text: "可为不同语言分别选择识别与合成模型。对提速明显的模型优先推荐 GPU；识别平均超过 500 ms 不推荐用于对话。"; role: "supporting" }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            ComboBox {
                objectName: "speechLanguage"
                width: Math.min(180, dialog.availableWidth)
                implicitHeight: 48
                model: ["日语", "英语", "中文", "韩语", "粤语", "德语", "法语", "西班牙语"]
                property var codes: ["ja", "en", "zh", "ko", "yue", "de", "fr", "es"]
                currentIndex: codes.indexOf(speechLibrary.language)
                enabled: !speechLibrary.busy
                Accessible.name: "本地语音语言"
                onActivated: speechLibrary.setFilter(codes[currentIndex], speechLibrary.scenario)
            }
            ComboBox {
                objectName: "speechScenario"
                width: Math.min(180, dialog.availableWidth)
                implicitHeight: 48
                model: ["实时对话", "材料转录", "朗读"]
                property var codes: ["conversation", "import", "reading"]
                currentIndex: codes.indexOf(speechLibrary.scenario)
                enabled: !speechLibrary.busy
                Accessible.name: "本地语音用途"
                onActivated: speechLibrary.setFilter(speechLibrary.language, codes[currentIndex])
            }
            MButton { objectName: "speechRefresh"; text: "刷新"; variant: "outlined"; enabled: !speechLibrary.busy; onClicked: speechLibrary.refresh() }
            MButton {
                objectName: "speechPairBenchmark"
                text: "配对测速"
                variant: "outlined"
                enabled: !speechLibrary.busy
                onClicked: { dialog.pairBenchmark = true; audioFile.open() }
            }
        }
        MLabel { objectName: "speechLibraryStatus"; text: speechLibrary.status; Accessible.role: Accessible.AlertMessage }
        ProgressBar { Layout.fillWidth: true; visible: speechLibrary.busy; indeterminate: speechLibrary.progress === 0; value: speechLibrary.progress }
        MButton { objectName: "speechCancel"; text: "取消当前任务"; variant: "outlined"; visible: speechLibrary.busy; onClicked: speechLibrary.cancel() }
        MLabel { visible: speechLibrary.models.length === 0 && !speechLibrary.busy; text: "这个语言/用途暂时没有候选模型。" }
        Repeater {
            model: speechLibrary.models
            MCard {
                required property var modelData
                objectName: "speechModel-" + modelData.id
                visible: !modelData.excluded && modelData.downloadBytes > 0
                MLabel { text: modelData.name + " · " + modelData.task; role: "title" }
                MLabel { visible: modelData.recommended; text: "本机计算延迟较低的候选；识别准确率、音质与完整链路仍需验收。"; role: "label" }
                MLabel { text: modelData.device.toUpperCase() + " · " + modelData.streaming; role: "supporting" }
                MLabel { text: modelData.deviceNote + (modelData.vramEstimateMiB > 0 ? " · 显存准入估算 " + modelData.vramEstimateMiB + " MiB，非硬上限" : ""); role: "supporting" }
                MLabel { text: modelData.notes; role: "supporting" }
                MLabel {
                    visible: modelData.downloadBytes > 0
                    text: "下载 " + modelData.downloadMiB + " MiB · 展开大小上限 " + modelData.unpackedLimitMiB + " MiB · 测速进程预算 " + modelData.evaluationBudgetMiB + " MiB（另留系统余量）"
                    role: "supporting"
                }
                MLabel { text: modelData.measurement; role: "label" }
                MLabel { text: modelData.budgetStatus; role: "supporting" }
                MLabel { text: modelData.installed ? "已安装 · " + modelData.installedMiB + " MiB" : modelData.reason; role: "supporting" }
                MLabel { text: modelData.license; role: "supporting" }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    MButton {
                        objectName: "speechInstall-" + modelData.id
                        text: "下载 / 继续"
                        visible: !modelData.installed && modelData.downloadBytes > 0
                        enabled: !speechLibrary.busy && modelData.downloadable
                        onClicked: speechLibrary.install(modelData.id)
                    }
                    MButton {
                        objectName: "speechBenchmark-" + modelData.id
                        text: "本机测速"
                        visible: modelData.installed
                        enabled: !speechLibrary.busy
                        onClicked: {
                            if (modelData.task === "STT") {
                                dialog.pendingModel = modelData.id
                                dialog.pairBenchmark = false
                                audioFile.open()
                            } else speechLibrary.runBenchmark(modelData.id, "")
                        }
                    }
                    MButton { text: "试听"; visible: modelData.preview.length > 0; enabled: !speechLibrary.busy; variant: "tonal"; onClicked: speechLibrary.preview(modelData.id) }
                    MButton { text: "停止试听"; visible: modelData.preview.length > 0; variant: "text"; onClicked: speechLibrary.stopPreview() }
                    MButton {
                        objectName: "speechSelect-" + modelData.id
                        text: modelData.selected ? "已选用" : "选用模型"
                        visible: modelData.installed
                        enabled: !speechLibrary.busy && modelData.measured
                        variant: "outlined"
                        onClicked: speechLibrary.select(modelData.id)
                    }
                    MButton { text: "校验"; visible: modelData.installed; enabled: !speechLibrary.busy; variant: "text"; onClicked: speechLibrary.verify(modelData.id) }
                    MButton {
                        text: "卸载"
                        visible: modelData.installed
                        enabled: !speechLibrary.busy
                        variant: "text"
                        onClicked: { dialog.uninstallModel = modelData.id; removeDialog.open() }
                    }
                    MButton { text: "来源与许可"; variant: "text"; onClicked: Qt.openUrlExternally(modelData.source) }
                }
            }
        }
        MLabel { text: "缓存位置：" + speechLibrary.cachePath; role: "supporting" }
        MLabel { text: "所选测速录音不会复制或上传。对话模型用于当前桌面分轮语音；计算与加速中可切回已配置的远程语音。"; role: "supporting" }
    }
}
