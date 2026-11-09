import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

MButton {
    id: control
    property string helpText: ""
    text: qsTr("说明")
    variant: "text"
    Accessible.description: helpText
    onClicked: help.open()
    Popup {
        id: help
        objectName: control.objectName + "-popup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(440, parent ? parent.width - 24 : 360)
        padding: 16
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: AppTheme.surfaceContainerHigh; radius: 8; border.color: AppTheme.outlineVariant }
        contentItem: ColumnLayout {
            spacing: 8
            MLabel { text: control.helpText }
            MButton { text: qsTr("关闭"); variant: "text"; Layout.alignment: Qt.AlignRight; onClicked: help.close() }
        }
    }
}
