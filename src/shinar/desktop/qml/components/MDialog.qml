import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import "../design"

Dialog {
    id: dialog
    modal: true
    Material.roundedScale: Material.ExtraLargeScale
    Material.background: AppTheme.surfaceContainerHigh
    padding: 24
    // Material's shader elevation can hide the surface on Qt's software renderer.
    background: Rectangle {
        color: AppTheme.surfaceContainerHigh
        radius: AppTheme.dialogRadius
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: AppTheme.duration }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: AppTheme.duration }
    }
}
