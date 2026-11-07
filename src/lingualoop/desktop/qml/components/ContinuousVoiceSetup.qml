import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

ColumnLayout {
    id: pane
    required property var controller
    readonly property bool preparing: controller.connectionState === "preparing"
    readonly property bool ready: controller.assetsReady && controller.environmentReady
    Layout.fillWidth: true
    spacing: 8
    Component.onCompleted: if (visible) controller.refreshSetupStorage()
    onVisibleChanged: if (visible) controller.refreshSetupStorage()
    MLabel { text: qsTr("连续语音组件"); role: "label" }
    MLabel { text: pane.ready ? qsTr("已准备。点击开始语音后才开启持续监听。") : qsTr("包含语音连接、回声处理、人声检测及独立运行环境；准备期间不开麦。"); role: "supporting"; font.pixelSize: 12 }
    SpeechPreparationSize {
        visible: !pane.ready
        downloadMiB: controller.setupSizes.downloadMiB
        requiredFreeMiB: controller.setupSizes.requiredFreeMiB
        explain: true
    }
    SpeechStorageUsage { objectName: "continuousStorageUsage"; usage: controller.setupStorage }
    MLabel { text: qsTr("按本地文件大小统计，硬链接只计一次；不含软件安装目录、学习资料或 STT/TTS 模型。运行内存取决于实际使用。"); role: "supporting"; font.pixelSize: 12 }
    ColumnLayout {
        visible: pane.preparing
        Layout.fillWidth: true; spacing: 4
        MLabel { objectName: "continuousSetupStage"; text: controller.setupProgress.phaseText; role: "supporting" }
        MLabel { objectName: "continuousSetupComponent"; visible: text.length > 0; text: controller.setupProgress.component; role: "supporting"; font.pixelSize: 12 }
        ProgressBar { objectName: "continuousSetupProgress"; Layout.fillWidth: true; indeterminate: controller.setupProgress.indeterminate; value: controller.setupProgress.progress }
        MLabel { objectName: "continuousSetupFileProgress"; visible: controller.setupProgress.transferText.length > 0; text: qsTr("当前文件：%1；文件完成后继续校验、安装和验证。").arg(controller.setupProgress.transferText); role: "supporting"; font.pixelSize: 12 }
    }
    Flow {
        Layout.fillWidth: true; spacing: 8
        MButton { objectName: "prepareContinuousVoice"; text: pane.preparing ? qsTr("正在准备…") : pane.ready ? qsTr("重新检查组件") : qsTr("准备连续语音组件"); variant: "outlined"; enabled: !learningViewModel.busy && !controller.active; onClicked: controller.prepare() }
        MButton { objectName: "cancelContinuousSetup"; visible: pane.preparing; text: qsTr("取消准备"); variant: "text"; onClicked: controller.stop() }
    }
    MLabel { text: controller.noticeText; visible: text.length > 0; role: "supporting" }
    MLabel { text: controller.errorText; visible: text.length > 0; color: AppTheme.error; role: "supporting" }
}
