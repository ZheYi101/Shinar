import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

MDialog {
    id: dialog
    objectName: "shutdownDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(420, parent.width - 24)
    title: qsTr("正在退出 LinguaLoop")
    visible: desktopShutdown.state === "closing"
    closePolicy: Popup.NoAutoClose
    Overlay.modal: Rectangle { color: AppTheme.scrim }
    contentItem: ColumnLayout {
        spacing: 16
        MLabel {
            Layout.fillWidth: true
            text: desktopShutdown.error || qsTr("正在停止语音并清理后台任务…")
        }
        MButton {
            visible: desktopShutdown.error.length > 0
            text: qsTr("重试退出")
            onClicked: desktopShutdown.quit()
        }
    }
}
