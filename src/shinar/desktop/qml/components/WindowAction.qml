import QtQuick
import QtQuick.Controls
import "../design"

AbstractButton {
    id: control
    property string glyph: "minimize"
    property string label: ""
    readonly property color glyphColor: glyph === "close" && (hovered || down) ? "#FFFFFF" : AppTheme.colorOnSurface
    implicitWidth: 48; implicitHeight: AppTheme.topBarHeight
    hoverEnabled: true
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    Accessible.name: label
    ToolTip.visible: hovered
    ToolTip.text: label
    ToolTip.delay: 650
    background: Rectangle {
        radius: 4
        color: control.glyph === "close" && (control.hovered || control.down) ? "#C42B1C" : control.down ? AppTheme.surfaceContainerHigh : control.hovered || control.visualFocus ? AppTheme.surfaceContainer : "transparent"
        Behavior on color { ColorAnimation { duration: AppTheme.motionFast } }
        border.width: control.visualFocus ? 2 : 0
        border.color: AppTheme.primary
    }
    contentItem: Item {
        Rectangle { visible: control.glyph === "minimize"; anchors.centerIn: parent; width: 12; height: 1.5; color: AppTheme.colorOnSurface }
        Rectangle { visible: control.glyph === "maximize"; anchors.centerIn: parent; width: 12; height: 12; color: "transparent"; border.width: 1.5; border.color: AppTheme.colorOnSurface }
        Item {
            visible: control.glyph === "restore"; anchors.centerIn: parent; width: 15; height: 15
            Rectangle { x: 4; width: 10; height: 10; color: "transparent"; border.width: 1.5; border.color: AppTheme.colorOnSurface }
            Rectangle { y: 4; width: 10; height: 10; color: AppTheme.surface; border.width: 1.5; border.color: AppTheme.colorOnSurface }
        }
        Item {
            visible: control.glyph === "close"; anchors.centerIn: parent; width: 14; height: 14
            Rectangle { anchors.centerIn: parent; width: 16; height: 1.5; rotation: 45; color: control.glyphColor }
            Rectangle { anchors.centerIn: parent; width: 16; height: 1.5; rotation: -45; color: control.glyphColor }
        }
        Text { visible: control.glyph === "more"; anchors.centerIn: parent; text: "···"; font.pixelSize: 24; color: AppTheme.colorOnSurface }
    }
}

