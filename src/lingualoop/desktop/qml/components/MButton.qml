import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "../design"

Button {
    id: control
    property string variant: "filled"
    readonly property color contentColor: !enabled ? Qt.alpha(AppTheme.colorOnSurface, 0.38) : variant === "filled" ? AppTheme.colorOnPrimary : variant === "tonal" ? AppTheme.colorOnSecondaryContainer : AppTheme.primary
    implicitHeight: AppTheme.touchTarget
    implicitWidth: Math.max(48, implicitContentWidth + leftPadding + rightPadding)
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.labelLarge
    font.weight: Font.Medium
    // The project supplies the semantic colors; Qt's highlighted palette uses
    // its own contrast color instead of Material.foreground.
    highlighted: false
    flat: variant === "text" || variant === "outlined"
    hoverEnabled: true
    leftPadding: 12
    rightPadding: 12
    icon.width: 24
    icon.height: 24
    icon.color: contentColor
    Material.roundedScale: Material.SmallScale
    Material.elevation: 0
    Material.background: variant === "text" || variant === "outlined" ? "transparent" : variant === "tonal" ? AppTheme.secondaryContainer : AppTheme.primary
    Material.foreground: contentColor
    Material.accent: AppTheme.primary
    Accessible.name: text
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: AppTheme.gapSmall
            IconLabel { visible: control.icon.source.toString().length > 0; iconSource: control.icon.source; tint: control.contentColor; width: 24; height: 24; anchors.verticalCenter: parent.verticalCenter }
            Text { text: control.text; font: control.font; color: control.contentColor; textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    background: Rectangle {
        implicitHeight: 40
        radius: 5
        color: control.flat ? "transparent" : !control.enabled ? Qt.alpha(AppTheme.colorOnSurface, 0.12) : control.Material.background
        border.width: control.variant === "outlined" || control.visualFocus ? 1 : 0
        border.color: control.visualFocus ? AppTheme.primary : AppTheme.outline
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: control.Material.foreground
            opacity: !control.enabled ? 0 : control.down || control.visualFocus ? 0.12 : control.hovered ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: AppTheme.duration } }
        }
    }
}
