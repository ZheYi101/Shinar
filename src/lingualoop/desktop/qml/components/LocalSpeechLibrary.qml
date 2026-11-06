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
        objectName: "speechBenchmarkFile"
        title: qsTr("选择本地测速录音（16kHz、单声道、16-bit PCM、最多 60 秒）")
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
        title: qsTr("卸载所选语音模型？")
        width: Math.min(440, Overlay.overlay ? Overlay.overlay.width - 32 : 360)
        implicitHeight: 240
        standardButtons: Dialog.Ok | Dialog.Cancel
        contentItem: ScrollView {
            contentWidth: availableWidth; clip: true
            Text { text: qsTr("会删除这个模型包、下载缓存及候选选择。学习材料和对话历史保留。"); wrapMode: Text.Wrap; width: parent.width; color: AppTheme.colorOnSurface; font.family: AppTheme.uiFont; font.pixelSize: AppTheme.bodyMedium }
        }
        onAccepted: speechLibrary.uninstall(dialog.uninstallModel)
    }
    ColumnLayout {
        width: dialog.availableWidth
        spacing: AppTheme.gapLarge
        Flow {
            Layout.fillWidth: true
            spacing: 8
            MComboBox {
                objectName: "speechLanguage"
                width: Math.min(180, dialog.availableWidth)
                implicitHeight: 48
                model: [qsTr("日语"), qsTr("英语"), qsTr("中文"), qsTr("韩语"), qsTr("粤语"), qsTr("德语"), qsTr("法语"), qsTr("西班牙语")]
                property var codes: ["ja", "en", "zh", "ko", "yue", "de", "fr", "es"]
                currentIndex: codes.indexOf(speechLibrary.language)
                enabled: !speechLibrary.busy
                Accessible.name: qsTr("本地语音语言")
                onActivated: speechLibrary.setFilter(codes[currentIndex], speechLibrary.scenario)
            }
            MComboBox {
                objectName: "speechScenario"
                width: Math.min(180, dialog.availableWidth)
                implicitHeight: 48
                model: [qsTr("实时对话"), qsTr("材料转录"), qsTr("朗读")]
                property var codes: ["conversation", "import", "reading"]
                currentIndex: codes.indexOf(speechLibrary.scenario)
                enabled: !speechLibrary.busy
                Accessible.name: qsTr("本地语音用途")
                onActivated: speechLibrary.setFilter(speechLibrary.language, codes[currentIndex])
            }
            MButton { objectName: "speechRefresh"; text: qsTr("刷新"); variant: "outlined"; enabled: !speechLibrary.busy; onClicked: speechLibrary.refresh() }
            MButton {
                objectName: "speechPairBenchmark"
                text: qsTr("配对测速")
                variant: "outlined"
                enabled: !speechLibrary.busy
                onClicked: { dialog.pairBenchmark = true; audioFile.open() }
            }
        }
        MLabel { objectName: "speechLibraryStatus"; text: speechLibrary.status; Accessible.role: Accessible.AlertMessage }
        ProgressBar { Layout.fillWidth: true; visible: speechLibrary.busy; indeterminate: speechLibrary.progress === 0; value: speechLibrary.progress }
        MLabel { visible: speechLibrary.busy && speechLibrary.progress > 0; text: qsTr("当前组件下载进度"); role: "supporting" }
        MButton { objectName: "speechCancel"; text: qsTr("取消当前任务"); variant: "outlined"; visible: speechLibrary.busy; onClicked: speechLibrary.cancel() }
        MLabel { visible: speechLibrary.models.length === 0 && !speechLibrary.busy; text: qsTr("这个语言/用途暂时没有候选模型。") }
        Repeater {
            model: speechLibrary.models
            MCard {
                id: speechModelCard
                required property var modelData
                property bool termsExpanded: false
                objectName: "speechModel-" + modelData.id
                visible: !modelData.excluded && modelData.downloadBytes > 0
                MLabel { text: modelData.name + " · " + modelData.task; role: "title" }
                MLabel { visible: modelData.recommended; text: qsTr("本机计算延迟较低的候选；识别准确率、音质与完整链路仍需验收。"); role: "label" }
                MLabel { text: modelData.device.toUpperCase() + " · " + modelData.streaming; role: "supporting" }
                MLabel { text: modelData.vramEstimateMiB > 0 ? qsTr("%1 · 显存准入估算 %2 MiB，非硬上限").arg(modelData.deviceNote).arg(modelData.vramEstimateMiB) : modelData.deviceNote; role: "supporting" }
                MLabel { text: modelData.notes; role: "supporting" }
                MLabel { text: modelData.runtimeReady ? qsTr("运行环境：已验证") : qsTr("运行环境：待准备"); role: "supporting" }
                MLabel { visible: modelData.setupError.length > 0; text: modelData.setupError; color: AppTheme.error; role: "supporting" }
                MLabel { visible: !modelData.runtimeReady || !modelData.installed; text: qsTr("本次需下载约 %1 MiB，准备空间约 %2 MiB（含运行库与共享资源）").arg(modelData.setupMiB).arg(modelData.setupDiskMiB); role: "supporting" }
                ColumnLayout {
                    visible: modelData.voices.length > 0; Layout.fillWidth: true; spacing: 4
                    MLabel { text: qsTr("声音 / 风格"); role: "label" }
                    MComboBox { objectName: "speechVoice-" + modelData.id; Layout.fillWidth: true; model: modelData.voices; textRole: "label"; currentIndex: model.findIndex(v => v.id === modelData.voiceId); enabled: !speechLibrary.busy; onActivated: speechLibrary.selectVoice(modelData.id, model[currentIndex].id) }
                    MLabel { text: qsTr("当前语音保持原声音；更改在下次绑定生效，连续语音需重新开始。"); role: "supporting" }
                }
                ColumnLayout {
                    visible: modelData.termsRequired; Layout.fillWidth: true
                    MButton { text: qsTr("查看此版本模型与角色条款"); variant: "text"; onClicked: speechModelCard.termsExpanded = !speechModelCard.termsExpanded }
                    ScrollView { visible: speechModelCard.termsExpanded; Layout.fillWidth: true; Layout.preferredHeight: 200; clip: true; contentWidth: availableWidth; TextArea { text: modelData.termsText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.family: AppTheme.uiFont; color: AppTheme.colorOnSurface; background: Rectangle { color: AppTheme.surfaceContainerLow } } }
                    CheckBox { objectName: "speechTerms-" + modelData.id; Layout.fillWidth: true; text: qsTr("已阅读并同意本版本语音模型与角色条款"); checked: modelData.termsAccepted; enabled: !speechLibrary.busy; onToggled: speechLibrary.acceptVoiceTerms(modelData.id, checked); contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap; leftPadding: parent.indicator.width + 8; verticalAlignment: Text.AlignVCenter } }
                    MLabel { text: "VOICEVOX:ずんだもん"; role: "supporting" }
                }
                MLabel {
                    visible: modelData.downloadBytes > 0
                    text: qsTr("下载 %1 MiB · 展开大小上限 %2 MiB · 测速进程预算 %3 MiB（另留系统余量）").arg(modelData.downloadMiB).arg(modelData.unpackedLimitMiB).arg(modelData.evaluationBudgetMiB)
                    role: "supporting"
                }
                MLabel { text: modelData.measurement; role: "label" }
                MLabel { text: modelData.budgetStatus; role: "supporting" }
                MLabel { text: modelData.installed ? qsTr("已安装 · %1 MiB").arg(modelData.installedMiB) : modelData.reason; role: "supporting" }
                MLabel { text: modelData.license; role: "supporting" }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    MButton {
                        objectName: "speechInstall-" + modelData.id
                        text: qsTr("准备 / 下载 / 继续")
                        visible: (!modelData.installed || !modelData.runtimeReady) && modelData.downloadBytes > 0
                        enabled: !speechLibrary.busy && modelData.downloadable
                        onClicked: speechLibrary.preparePackage(modelData.id)
                    }
                    MButton {
                        objectName: "speechBenchmark-" + modelData.id
                        text: qsTr("本机测速")
                        visible: modelData.installed
                        enabled: !speechLibrary.busy && modelData.benchmarkable
                        onClicked: {
                            if (modelData.task === "STT") {
                                dialog.pendingModel = modelData.id
                                dialog.pairBenchmark = false
                                audioFile.open()
                            } else speechLibrary.runBenchmark(modelData.id, "")
                        }
                    }
                    MButton { objectName: "speechPreview-" + modelData.id; text: qsTr("试听"); visible: modelData.preview.length > 0; enabled: !speechLibrary.busy; variant: "tonal"; onClicked: speechLibrary.preview(modelData.id) }
                    MButton { objectName: "speechStopPreview-" + modelData.id; text: qsTr("停止试听"); visible: modelData.preview.length > 0; variant: "text"; onClicked: speechLibrary.stopPreview() }
                    MButton {
                        objectName: "speechSelect-" + modelData.id
                        text: modelData.selected ? qsTr("已选用") : qsTr("选用模型")
                        visible: modelData.installed
                        enabled: !speechLibrary.busy && modelData.measured
                        variant: "outlined"
                        onClicked: speechLibrary.select(modelData.id)
                    }
                    MButton { text: qsTr("校验"); visible: modelData.installed; enabled: !speechLibrary.busy; variant: "text"; onClicked: speechLibrary.verify(modelData.id) }
                    MButton {
                        text: qsTr("卸载")
                        visible: modelData.installed
                        enabled: !speechLibrary.busy
                        variant: "text"
                        onClicked: { dialog.uninstallModel = modelData.id; removeDialog.open() }
                    }
                    MButton { text: qsTr("来源与许可"); variant: "text"; onClicked: Qt.openUrlExternally(modelData.source) }
                }
            }
        }
        MLabel { text: qsTr("缓存位置：%1").arg(speechLibrary.cachePath); role: "supporting" }
        MLabel { text: qsTr("所选测速录音不会复制或上传。模型按会话语言用于分轮与连续语音；计算与加速中可切回已配置的远程语音。"); role: "supporting" }
    }
}
