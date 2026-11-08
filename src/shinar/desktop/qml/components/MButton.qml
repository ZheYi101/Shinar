import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Controls.Material
import "../design"

Basic.Button {
    id: control
    property string variant: "filled"
    property int horizontalAlignment: Text.AlignHCenter
    readonly property color contentColor: !enabled ? Qt.alpha(AppTheme.colorOnSurface, 0.45) : variant === "filled" ? AppTheme.colorOnPrimary : variant === "tonal" ? AppTheme.colorOnPrimaryContainer : AppTheme.colorOnSurface
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
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    leftPadding: 12
    rightPadding: 12
    topPadding: 6
    bottomPadding: 6
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    icon.width: 24
    icon.height: 24
    icon.color: contentColor
    Material.roundedScale: Material.SmallScale
    Material.elevation: 0
    Material.background: variant === "text" || variant === "outlined" ? "transparent" : variant === "tonal" ? AppTheme.primaryContainer : AppTheme.primary
    Material.foreground: contentColor
    Material.accent: AppTheme.primary
    Accessible.name: text
    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        clip: true
        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            x: control.horizontalAlignment === Text.AlignLeft ? 0 : control.horizontalAlignment === Text.AlignRight ? parent.width-width : (parent.width-width)/2
            spacing: AppTheme.gapSmall
            IconLabel { visible: control.icon.source.toString().length > 0; iconSource: control.icon.source; tint: control.contentColor; width: 24; height: 24; anchors.verticalCenter: parent.verticalCenter }
            Text { text: control.text; font: control.font; color: control.contentColor; textFormat: Text.PlainText; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    background: Rectangle {
        implicitHeight: 40
        radius: 8
        color: control.flat ? "transparent" : !control.enabled ? Qt.alpha(AppTheme.colorOnSurface, 0.12) : control.Material.background
        border.width: control.variant === "outlined" || control.visualFocus ? 1 : 0
        border.color: control.visualFocus ? AppTheme.primary : AppTheme.outline
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: control.Material.foreground
            opacity: !control.enabled ? 0 : control.down || control.visualFocus ? 0.12 : control.hovered ? 0.08 : 0
            Behavior on opacity { NumberAnimation { duration: AppTheme.motionFast } }
        }
    }
}
