import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

Item {
    id: row
    required property var modelData
    property bool expanded: false
    property bool termsExpanded: false
    readonly property bool downloading: { speechLibrary.downloadRevision; return speechLibrary.hasDownload(modelData.id) }
    signal customBenchmarkRequested(string modelId)
    signal uninstallRequested(string modelId)
    objectName: "speechModel-" + modelData.id
    implicitHeight: body.implicitHeight + 22
    height: implicitHeight
    ColumnLayout {
        id: body
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: parent.top; anchors.topMargin: 10
        anchors.rightMargin: 12
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            MLabel { text: modelData.name; role: "label"; font.pixelSize: 15 }
            MLabel { text: modelData.selected ? qsTr("已选用") : modelData.recommended ? qsTr("低延迟候选") : ""; color: AppTheme.primary; font.pixelSize: 12; Layout.fillWidth: false }
        }
        MLabel {
            text: modelData.device.toUpperCase() + " · " + (modelData.installed ? qsTr("文件已安装") : qsTr("文件未安装"))
                  + " · " + (modelData.runtimeReady ? qsTr("环境已验证") : qsTr("环境未准备"))
                  + " · " + (modelData.measured ? qsTr("已测速") : qsTr("未测速"))
            role: "supporting"; font.pixelSize: 12
        }
        SpeechPreparationSize { id: preparationSize; visible: (!modelData.installed || !modelData.runtimeReady) && !row.downloading; downloadMiB: modelData.setupMiB; requiredFreeMiB: modelData.setupDiskMiB }
        MLabel { visible: modelData.setupError.length > 0; text: modelData.setupError; color: AppTheme.error; role: "supporting" }
        Flow {
            Layout.fillWidth: true; spacing: 6
            MButton {
                objectName: "speechInstall-" + modelData.id
                visible: !modelData.installed || !modelData.runtimeReady || row.downloading
                text: row.downloading ? qsTr("已加入下载") : modelData.installed ? qsTr("准备环境") : qsTr("下载模型")
                enabled: !speechLibrary.operationBusy && !row.downloading && modelData.downloadable
                variant: "outlined"
                onClicked: {
                    if (modelData.termsRequired && !modelData.termsAccepted) row.expanded = true
                    else speechLibrary.preparePackage(modelData.id)
                }
            }
            MButton {
                objectName: "speechBenchmark-" + modelData.id; visible: modelData.installed
                text: modelData.measured ? qsTr("重新测速") : qsTr("测速并选用")
                enabled: !speechLibrary.operationBusy && !row.downloading && modelData.runtimeReady && modelData.benchmarkable
                variant: "text"
                onClicked: {
                    if (modelData.measured) speechLibrary.runBenchmark(modelData.id, "")
                    else speechLibrary.benchmarkAndSelect(modelData.id)
                }
            }
            MButton { objectName: "speechPreview-" + modelData.id; visible: modelData.preview.length > 0; text: qsTr("试听"); enabled: !speechLibrary.operationBusy; variant: "text"; onClicked: speechLibrary.preview(modelData.id) }
            MButton { objectName: "speechStopPreview-" + modelData.id; visible: modelData.preview.length > 0 && row.expanded; text: qsTr("停止试听"); variant: "text"; onClicked: speechLibrary.stopPreview() }
            MButton { objectName: "speechSelect-" + modelData.id; visible: modelData.installed && modelData.measured; text: modelData.selected ? qsTr("已选用") : qsTr("选用"); enabled: !modelData.selected && !speechLibrary.operationBusy && !row.downloading; variant: "text"; onClicked: speechLibrary.select(modelData.id) }
            MButton { objectName: "speechDetails-" + modelData.id; text: row.expanded ? qsTr("收起详情") : qsTr("详情与声音"); variant: "text"; onClicked: row.expanded = !row.expanded }
        }
        ColumnLayout {
            visible: row.expanded
            Layout.fillWidth: true; spacing: 6
            MLabel { text: modelData.measurement; role: "label"; font.pixelSize: 13 }
            MLabel { text: modelData.budgetStatus; role: "supporting"; font.pixelSize: 12 }
            MButton { objectName: "speechCustomBenchmark-" + modelData.id; visible: modelData.installed && modelData.task === "STT"; text: qsTr("使用自己的录音测速…"); enabled: !speechLibrary.operationBusy && !row.downloading && modelData.runtimeReady && modelData.benchmarkable; variant: "text"; onClicked: row.customBenchmarkRequested(modelData.id) }
            MLabel { text: modelData.notes; role: "supporting"; font.pixelSize: 12 }
            MLabel { text: modelData.deviceNote + " · " + modelData.streaming; role: "supporting"; font.pixelSize: 12 }
            MLabel { visible: modelData.vramEstimateMiB > 0; text: qsTr("显存准入估算 %1 MiB").arg(modelData.vramEstimateMiB); role: "supporting"; font.pixelSize: 12 }
            ColumnLayout {
                visible: modelData.voices.length > 0
                Layout.fillWidth: true; spacing: 4
                MLabel { text: qsTr("声音 / 风格"); role: "label"; font.pixelSize: 13 }
                MComboBox {
                    objectName: "speechVoice-" + modelData.id; Layout.fillWidth: true
                    model: modelData.voices; textRole: "label"
                    currentIndex: model.findIndex(v => v.id === modelData.voiceId)
                    enabled: !speechLibrary.operationBusy && !row.downloading
                    Accessible.description: qsTr("更改声音在下次开始语音时生效。")
                    ToolTip.visible: hovered || activeFocus
                    ToolTip.text: Accessible.description
                    ToolTip.delay: 650
                    onActivated: speechLibrary.selectVoice(modelData.id, model[currentIndex].id)
                }
            }
            ColumnLayout {
                visible: modelData.termsRequired; Layout.fillWidth: true
                MButton { text: qsTr("查看此版本模型与角色条款"); variant: "text"; onClicked: row.termsExpanded = !row.termsExpanded }
                ScrollView { visible: row.termsExpanded; Layout.fillWidth: true; Layout.preferredHeight: 180; clip: true; contentWidth: availableWidth; TextArea { text: modelData.termsText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; font.family: AppTheme.uiFont; color: AppTheme.colorOnSurface; background: Rectangle { color: AppTheme.surfaceContainerLow } } }
                CheckBox { objectName: "speechTerms-" + modelData.id; Layout.fillWidth: true; text: qsTr("已阅读并同意本版本语音模型与角色条款"); checked: modelData.termsAccepted; enabled: !speechLibrary.operationBusy && !row.downloading; onToggled: speechLibrary.acceptVoiceTerms(modelData.id, checked); contentItem: Text { text: parent.text; font: parent.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap; leftPadding: parent.indicator.width + 8; verticalAlignment: Text.AlignVCenter } }
                MLabel { text: "VOICEVOX:ずんだもん"; role: "supporting"; font.pixelSize: 12 }
            }
            MLabel { objectName: "speechPackageSize-" + modelData.id; text: qsTr("模型下载包 %1 MiB（不含共享组件）").arg(modelData.downloadMiB); role: "supporting"; font.pixelSize: 12 }
            MLabel { text: qsTr("模型安装文件 %1 MiB · 模型下载缓存 %2 MiB").arg(modelData.installedMiB).arg(modelData.cacheMiB || 0); role: "supporting"; font.pixelSize: 12 }
            MLabel { objectName: "speechMemory-" + modelData.id; text: modelData.measurementStats && modelData.measurementStats.peak_mib > 0 ? qsTr("运行内存（RAM）实测 %1 MiB").arg(modelData.measurementStats.peak_mib.toFixed(0)) : qsTr("运行内存（RAM）：尚无本机实测"); role: "supporting"; font.pixelSize: 12 }
            MLabel { text: qsTr("测速内存预留 %1 MiB").arg(modelData.evaluationBudgetMiB); role: "supporting"; font.pixelSize: 12 }
            MHelpButton {
                objectName: "speechCapacityHelp-" + modelData.id
                text: qsTr("容量与内存说明")
                helpText: preparationSize.explanation + "\n\n" + qsTr("模型下载包仅含本模型的下载文件，共享运行环境另计；下载包大小不等于安装后的占用。模型安装文件和下载缓存也仅计本模型，缓存保留供复用与修复。运行内存不能从下载大小推算。测速内存预留和显存准入估算用于判断是否适合启动，不是实测占用或硬上限。")
            }
            MLabel { text: modelData.license; role: "supporting"; font.pixelSize: 12 }
            Flow {
                Layout.fillWidth: true; spacing: 6
                MButton { text: qsTr("校验文件"); visible: modelData.installed; enabled: !speechLibrary.operationBusy && !row.downloading; variant: "text"; onClicked: speechLibrary.verify(modelData.id) }
                MButton { text: qsTr("卸载"); visible: modelData.installed; enabled: !speechLibrary.operationBusy && !row.downloading; variant: "text"; onClicked: row.uninstallRequested(modelData.id) }
                MButton { text: qsTr("来源与许可"); variant: "text"; onClicked: Qt.openUrlExternally(modelData.source) }
            }
        }
    }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: AppTheme.outlineVariant }
}
