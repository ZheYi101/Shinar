import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.SpinBox {
    id: control
    implicitWidth: 142
    implicitHeight: 36
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.bodyMedium
    leftPadding: 34
    rightPadding: 34
    topInset: 0
    bottomInset: 0
    contentItem: TextInput {
        text: control.textFromValue(control.value, control.locale)
        font: control.font
        color: AppTheme.colorOnSurface
        selectionColor: AppTheme.primaryContainer
        selectedTextColor: AppTheme.colorOnSurface
        horizontalAlignment: Qt.AlignHCenter
        verticalAlignment: Qt.AlignVCenter
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
    }
    up.indicator: Rectangle {
        x: control.width-width
        width: 32; height: control.height
        color: control.up.pressed ? AppTheme.primaryContainer : "transparent"
        Text { anchors.centerIn: parent; text: "+"; font.pixelSize: 20; color: AppTheme.colorOnSurface; opacity: control.up.enabled ? 1 : 0.4 }
    }
    down.indicator: Rectangle {
        width: 32; height: control.height
        color: control.down.pressed ? AppTheme.primaryContainer : "transparent"
        Text { anchors.centerIn: parent; text: "−"; font.pixelSize: 20; color: AppTheme.colorOnSurface; opacity: control.down.enabled ? 1 : 0.4 }
    }
    background: Rectangle {
        color: AppTheme.dark ? AppTheme.surfaceContainer : "#FCF9F1"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? AppTheme.primary : AppTheme.outlineVariant
        radius: 4
    }
}
