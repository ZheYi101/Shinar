import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.ToolButton {
    id: control
    property string symbol: "info"
    property string label: ""
    property bool filled: false
    readonly property color contentColor: !enabled ? AppTheme.colorOnSurfaceVariant : filled ? AppTheme.colorOnPrimary : AppTheme.colorOnSurface
    implicitWidth: 36
    implicitHeight: 36
    padding: 8
    hoverEnabled: true
    display: Basic.AbstractButton.IconOnly
    icon.source: Qt.resolvedUrl("../assets/" + symbol + ".svg")
    icon.width: 20
    icon.height: 20
    icon.color: contentColor
    opacity: enabled ? 1 : 0.4
    text: label
    Accessible.name: label
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    Basic.ToolTip.visible: hovered && label.length > 0
    Basic.ToolTip.text: label
    Basic.ToolTip.delay: 650
    Basic.ToolTip.timeout: 3000
    background: Rectangle {
        radius: control.filled ? 18 : 8
        color: control.filled ? AppTheme.primary : control.down ? Qt.alpha(AppTheme.colorOnSurface, 0.13) : control.hovered ? Qt.alpha(AppTheme.colorOnSurface, 0.07) : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: AppTheme.primary
        scale: control.down ? 0.92 : 1
        Behavior on color { enabled: !control.filled; ColorAnimation { duration: AppTheme.motionFast } }
        Behavior on scale { NumberAnimation { duration: AppTheme.motionFast; easing.type: Easing.OutCubic } }
    }
}
