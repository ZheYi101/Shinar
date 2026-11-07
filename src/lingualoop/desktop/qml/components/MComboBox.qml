import QtQuick
import QtQuick.Controls.Basic as Basic
import "../design"

Basic.ComboBox {
    id: control
    implicitHeight: 36
    implicitWidth: Math.max(120, implicitContentWidth + leftPadding + rightPadding)
    font.family: AppTheme.uiFont
    font.pixelSize: AppTheme.bodyMedium
    leftPadding: 12
    rightPadding: 32
    topPadding: 7
    bottomPadding: 7
    topInset: 0
    bottomInset: 0
    spacing: 8
    hoverEnabled: true
    HoverHandler { cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    contentItem: Text {
        textFormat: Text.PlainText
        text: control.displayText
        font: control.font
        color: control.enabled ? AppTheme.colorOnSurface : AppTheme.colorOnSurfaceVariant
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
    }
    indicator: Item {
        x: control.width - width - 12
        y: (control.height-height)/2
        width: 10; height: 8
        rotation: control.popup.visible ? 180 : 0
        Behavior on rotation { NumberAnimation { duration: AppTheme.motionFast; easing.type: Easing.OutCubic } }
        Rectangle { x: 1; y: 2; width: 6; height: 1.3; rotation: 45; color: AppTheme.colorOnSurface }
        Rectangle { x: 5; y: 2; width: 6; height: 1.3; rotation: -45; color: AppTheme.colorOnSurface }
    }
    background: Rectangle {
        radius: 8
        color: control.down || control.hovered ? AppTheme.surfaceContainer : AppTheme.dark ? AppTheme.surfaceContainer : "#FCF9F1"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus || control.hovered ? AppTheme.primary : AppTheme.outlineVariant
        Behavior on color { ColorAnimation { duration: AppTheme.motionFast } }
        Behavior on border.color { ColorAnimation { duration: AppTheme.motionFast } }
        opacity: control.enabled ? 1 : 0.6
    }
    delegate: Basic.ItemDelegate {
        required property int index
        width: ListView.view.width
        implicitHeight: Math.max(36, implicitContentHeight + 16)
        font: control.font
        text: control.textAt(index)
        highlighted: control.highlightedIndex === index
        hoverEnabled: control.hoverEnabled
        contentItem: Text { text: parent.text; textFormat: Text.PlainText; font: control.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        // ComboBox owns pointer and keyboard highlighting; switch rows without a fade trail.
        background: Rectangle { radius: 6; color: parent.highlighted ? AppTheme.primaryContainer : "transparent" }
    }
    popup: Basic.Popup {
        objectName: control.objectName + "-popup"
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 320)
        padding: 4
        margins: 8
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            highlightMoveDuration: 0
            Basic.ScrollIndicator.vertical: Basic.ScrollIndicator { }
        }
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 10 }
    }
}
