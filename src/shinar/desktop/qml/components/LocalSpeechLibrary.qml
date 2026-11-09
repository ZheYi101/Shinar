import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../design"

ColumnLayout {
    id: page
    spacing: 8
    signal openCompute()
    signal openStorage()
    property string pendingModel: ""
    property string uninstallModel: ""
    property bool pairBenchmark: false
    property string taskFilter: "STT"
    property var expandedModels: ({})
    readonly property var availableModels: speechLibrary.models.filter(m => !m.excluded && m.downloadBytes > 0)
    readonly property var shownModels: availableModels.filter(m => m.task === page.taskFilter)
    onShownModelsChanged: modelAutoScroll.stop()
    onVisibleChanged: {
        if (visible && !speechLibrary.operationBusy) speechLibrary.refresh()
        else if (!visible) speechLibrary.stopPreview()
    }
    onAvailableModelsChanged: {
        if (shownModels && !shownModels.length && availableModels.length) taskFilter = availableModels[0].task
    }
    FileDialog {
        id: audioFile
        objectName: "speechBenchmarkFile"
        title: qsTr("选择本地测速录音（16kHz、单声道、16-bit PCM、最多 60 秒）")
        nameFilters: ["PCM WAV (*.wav)"]
        onAccepted: {
            if (page.pairBenchmark) speechLibrary.runPairBenchmark(selectedFile.toString())
            else speechLibrary.runBenchmark(page.pendingModel, selectedFile.toString())
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
        onAccepted: speechLibrary.uninstall(page.uninstallModel)
    }
    Flow {
        Layout.fillWidth: true; spacing: 6
        MComboBox {
            objectName: "speechLanguage"; width: Math.min(150, page.width); implicitHeight: 36
            model: [qsTr("日语"), qsTr("英语"), qsTr("中文"), qsTr("韩语"), qsTr("粤语"), qsTr("德语"), qsTr("法语"), qsTr("西班牙语")]
            property var codes: ["ja", "en", "zh", "ko", "yue", "de", "fr", "es"]
            currentIndex: codes.indexOf(speechLibrary.language)
            enabled: !speechLibrary.operationBusy; Accessible.name: qsTr("本地语音语言")
            onActivated: speechLibrary.setFilter(codes[currentIndex], speechLibrary.scenario)
        }
        MComboBox {
            objectName: "speechScenario"; width: Math.min(150, page.width); implicitHeight: 36
            model: [qsTr("实时对话"), qsTr("材料转录"), qsTr("朗读")]
            property var codes: ["conversation", "import", "reading"]
            currentIndex: codes.indexOf(speechLibrary.scenario)
            enabled: !speechLibrary.operationBusy; Accessible.name: qsTr("本地语音用途")
            onActivated: speechLibrary.setFilter(speechLibrary.language, codes[currentIndex])
        }
        MButton { objectName: "speechRefresh"; text: qsTr("刷新"); variant: "text"; enabled: !speechLibrary.operationBusy; onClicked: speechLibrary.refresh() }
        MButton { objectName: "speechPairBenchmark"; text: qsTr("配对测速"); variant: "text"; enabled: !speechLibrary.operationBusy && speechLibrary.downloadCount === 0; onClicked: speechLibrary.runPairBenchmark("") }
        MButton { objectName: "openSpeechCompute"; text: qsTr("计算与加速"); variant: "outlined"; onClicked: page.openCompute() }
        MButton { objectName: "openSpeechStorage"; text: qsTr("存储管理"); variant: "text"; onClicked: page.openStorage() }
        MHelpButton {
            objectName: "speechBenchmarkHelp"
            text: qsTr("测速说明")
            helpText: qsTr("测速使用内置示例；也可在模型详情中选择自己的录音。首次通过“测速并选用”后，模型用于当前语言和用途；实时语音对话需在“实时对话”下选用。")
        }
    }
    MLabel { objectName: "speechLibraryStatus"; visible: text.length > 0; text: speechLibrary.status; role: "supporting"; Accessible.role: Accessible.AlertMessage }
    SpeechStorageUsage {
        objectName: "speechStorageUsage"; usage: speechLibrary.storageUsage; collapsible: true
        explanation: qsTr("这里是已存到本机的语音文件，包含模型、共享运行环境和缓存；不含软件本身或学习资料。硬链接只计一次。各模型的下载量和安装预留空间见列表，运行内存见详情。")
    }
    RowLayout {
        visible: speechLibrary.operationBusy
        Layout.fillWidth: true
        ProgressBar { Layout.fillWidth: true; indeterminate: speechLibrary.progress === 0; value: speechLibrary.progress }
        MButton { objectName: "speechCancel"; text: qsTr("取消操作"); variant: "text"; onClicked: speechLibrary.cancel() }
    }
    SpeechDownloadJobs { Layout.fillWidth: true }
    MLabel { objectName: "speechSelectionSummary"; text: qsTr("识别：%1 · 合成：%2").arg((speechLibrary.models.find(m => m.task === "STT" && m.selected) || {}).name || qsTr("未选用")).arg((speechLibrary.models.find(m => m.task === "TTS" && m.selected) || {}).name || qsTr("未选用")); role: "supporting" }
    RowLayout {
        Layout.fillWidth: true; spacing: 8
        MButton { objectName: "speechTabSTT"; text: qsTr("语音识别 STT (%1)").arg(page.availableModels.filter(m => m.task === "STT").length); variant: page.taskFilter === "STT" ? "tonal" : "text"; onClicked: { page.taskFilter = "STT"; models.positionViewAtBeginning() } }
        MButton { objectName: "speechTabTTS"; text: qsTr("语音合成 TTS (%1)").arg(page.availableModels.filter(m => m.task === "TTS").length); variant: page.taskFilter === "TTS" ? "tonal" : "text"; onClicked: { page.taskFilter = "TTS"; models.positionViewAtBeginning() } }
        Item { Layout.fillWidth: true }
    }
    Item {
        Layout.fillWidth: true; Layout.fillHeight: true
        ScrollView {
            id: modelScroll
            objectName: "speechModelsPage"
            anchors.fill: parent
            contentWidth: availableWidth; clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical: ScrollBar {
                objectName: "speechModelScrollBar"
                parent: modelScroll
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: parent.right
                orientation: Qt.Vertical
                policy: ScrollBar.AsNeeded
                interactive: true
                width: 10
                minimumSize: 0.08
                contentItem: Rectangle { implicitWidth: 6; radius: 3; color: parent.pressed ? AppTheme.primary : AppTheme.outline; opacity: parent.hovered || parent.pressed ? 0.85 : 0.55 }
            }
            ListView {
                id: models
                model: page.shownModels
                contentWidth: width
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                maximumFlickVelocity: 2200
                flickDeceleration: 2500
                pixelAligned: true
                cacheBuffer: 1200
                delegate: SpeechModelRow {
                    width: ListView.view.width
                    expanded: !!page.expandedModels[modelData.id]
                    onExpandedChanged: page.expandedModels[modelData.id] = expanded
                    onCustomBenchmarkRequested: function(modelId) { page.pendingModel = modelId; page.pairBenchmark = false; audioFile.open() }
                    onUninstallRequested: function(modelId) { page.uninstallModel = modelId; removeDialog.open() }
                }
                MLabel { visible: models.count === 0 && !speechLibrary.operationBusy; width: models.width; text: qsTr("这个语言和用途暂时没有此类候选模型。"); role: "supporting" }
            }
        }
        MiddleButtonAutoScroll {
            id: modelAutoScroll
            objectName: "speechModelAutoScroll"
            anchors.fill: parent
            anchors.rightMargin: modelScroll.ScrollBar.vertical.width
            target: models
        }
    }
}
