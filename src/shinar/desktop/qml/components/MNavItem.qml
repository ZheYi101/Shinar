import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

AbstractButton {
    id: control
    property string symbol: "chat_bubble"
    implicitWidth: 80
    implicitHeight: 72
    checkable: true
    hoverEnabled: true
    Accessible.name: text
    contentItem: ColumnLayout {
        spacing: 4
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 56
            Layout.preferredHeight: 32
            radius: 16
            color: control.checked ? AppTheme.secondaryContainer : control.down ? AppTheme.surfaceContainerHigh : control.hovered || control.visualFocus ? AppTheme.surfaceContainer : "transparent"
            IconLabel {
                anchors.centerIn: parent
                iconSource: Qt.resolvedUrl("../assets/" + control.symbol + ".svg")
                tint: control.checked ? AppTheme.colorOnSecondaryContainer : AppTheme.colorOnSurfaceVariant
            }
            border.width: control.visualFocus ? 2 : 0
            border.color: AppTheme.primary
            Behavior on color { ColorAnimation { duration: AppTheme.duration } }
        }
        Label {
            Layout.alignment: Qt.AlignHCenter
            text: control.text
            color: AppTheme.colorOnSurface
            font.family: AppTheme.uiFont
            font.pixelSize: 12
            font.weight: control.checked ? Font.DemiBold : Font.Normal
        }
    }
    background: Item {}
}
