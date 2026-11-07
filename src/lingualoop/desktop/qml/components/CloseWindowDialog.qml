import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

MDialog {
    id: dialog
    objectName: "closeWindowDialog"
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(440, parent.width - 24)
    title: qsTr("关闭 LinguaLoop")
    visible: desktopLifecycle.closePromptVisible
    // Release the modal overlay before the native window is hidden.
    exit: Transition { }
    Overlay.modal: Rectangle { color: AppTheme.scrim }
    closePolicy: Popup.CloseOnEscape
    onAboutToShow: remember.checked = false
    onRejected: desktopLifecycle.cancelClose()
    contentItem: ColumnLayout {
        spacing: 16
        MLabel {
            Layout.fillWidth: true
            text: qsTr("要继续在后台运行，还是退出程序？")
        }
        MLabel {
            Layout.fillWidth: true
            role: "supporting"
            text: qsTr("后台运行时，准备、下载和当前语音会继续。可从系统托盘重新打开窗口或退出。")
        }
        CheckBox {
            id: remember
            objectName: "rememberCloseChoice"
            text: qsTr("记住选择")
            Accessible.name: text
        }
        MButton {
            objectName: "closeToBackgroundButton"
            Layout.fillWidth: true
            text: qsTr("后台运行")
            enabled: desktopLifecycle.backgroundAvailable
            onClicked: desktopLifecycle.chooseCloseBehavior("background", remember.checked)
        }
        RowLayout {
            Layout.fillWidth: true
            MButton {
                objectName: "cancelWindowCloseButton"
                Layout.fillWidth: true
                text: qsTr("取消")
                variant: "text"
                onClicked: desktopLifecycle.cancelClose()
            }
            MButton {
                objectName: "quitApplicationButton"
                Layout.fillWidth: true
                text: qsTr("退出程序")
                variant: "outlined"
                onClicked: desktopLifecycle.chooseCloseBehavior("quit", remember.checked)
            }
        }
    }
}
