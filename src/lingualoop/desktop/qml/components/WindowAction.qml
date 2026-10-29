import QtQuick
import QtQuick.Controls
import "../design"

AbstractButton {
    id: control
    property string glyph: "minimize"
    property string label: ""
    implicitWidth: 48; implicitHeight: AppTheme.topBarHeight
    hoverEnabled: true
    Accessible.name: label
    ToolTip.visible: hovered
    ToolTip.text: label
    background: Rectangle {
        radius: AppTheme.cardRadius
        color: control.down ? AppTheme.surfaceContainerHigh : control.hovered || control.visualFocus ? AppTheme.surfaceContainer : "transparent"
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
            Rectangle { anchors.centerIn: parent; width: 16; height: 1.5; rotation: 45; color: AppTheme.colorOnSurface }
            Rectangle { anchors.centerIn: parent; width: 16; height: 1.5; rotation: -45; color: AppTheme.colorOnSurface }
        }
        Text { visible: control.glyph === "more"; anchors.centerIn: parent; text: "···"; font.pixelSize: 24; color: AppTheme.colorOnSurface }
    }
}

