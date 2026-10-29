import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.Switch {
    id: control
    implicitHeight: 36
    implicitWidth: 40 + (text.length ? 10 + implicitContentWidth : 0)
    spacing: 10
    padding: 0
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.bodyMedium
    indicator: Rectangle {
        implicitWidth: 38; implicitHeight: 22
        y: (control.height-height)/2
        radius: 11
        color: control.checked ? AppTheme.primary : AppTheme.outlineVariant
        opacity: control.enabled ? 1 : 0.45
        Rectangle {
            x: control.checked ? 18 : 3
            y: 3; width: 16; height: 16; radius: 8
            color: AppTheme.colorOnPrimary
            Behavior on x { NumberAnimation { duration: AppTheme.duration } }
        }
        border.width: control.visualFocus ? 2 : 0
        border.color: AppTheme.colorOnSurface
    }
    contentItem: Text {
        leftPadding: control.text.length ? 48 : 0
        text: control.text; font: control.font; color: AppTheme.colorOnSurface
        verticalAlignment: Text.AlignVCenter
    }
}
