import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.ItemDelegate {
    id: control
    property string symbol: ""
    property bool selected: false
    property bool collapsed: false
    implicitHeight: 38
    leftPadding: 10
    rightPadding: 10
    spacing: 10
    hoverEnabled: true
    font.family: AppTheme.uiFont
    font.pixelSize: 13
    font.weight: selected ? Font.Medium : Font.Normal
    display: collapsed ? Basic.AbstractButton.IconOnly : Basic.AbstractButton.TextBesideIcon
    icon.source: symbol ? Qt.resolvedUrl("../assets/" + symbol + ".svg") : ""
    icon.width: 18
    icon.height: 18
    icon.color: AppTheme.colorOnSurface
    palette.text: AppTheme.colorOnSurface
    palette.highlightedText: AppTheme.colorOnSurface
    Accessible.name: text
    Basic.ToolTip.visible: hovered && collapsed
    Basic.ToolTip.text: text
    Basic.ToolTip.delay: 650
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    background: Rectangle {
        radius: 8
        color: control.down ? Qt.alpha(AppTheme.colorOnSurface, 0.13) : control.selected ? Qt.alpha(AppTheme.primary, 0.13) : control.hovered ? Qt.alpha(AppTheme.colorOnSurface, 0.065) : "transparent"
        border.width: control.visualFocus ? 1 : 0
        border.color: AppTheme.primary
        Behavior on color { ColorAnimation { duration: AppTheme.motionFast } }
    }
}
