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
    contentItem: Text {
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
        Rectangle { x: 1; y: 2; width: 6; height: 1.3; rotation: 45; color: AppTheme.colorOnSurface }
        Rectangle { x: 5; y: 2; width: 6; height: 1.3; rotation: -45; color: AppTheme.colorOnSurface }
    }
    background: Rectangle {
        radius: 4
        color: control.down ? AppTheme.surfaceContainer : AppTheme.dark ? AppTheme.surfaceContainer : "#FCF9F1"
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? AppTheme.primary : AppTheme.outlineVariant
        opacity: control.enabled ? 1 : 0.6
    }
    delegate: Basic.ItemDelegate {
        required property int index
        width: control.popup.width - 2
        implicitHeight: Math.max(36, implicitContentHeight + 16)
        font: control.font
        text: control.textAt(index)
        highlighted: control.highlightedIndex === index
        contentItem: Text { text: parent.text; font: control.font; color: AppTheme.colorOnSurface; wrapMode: Text.Wrap; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: parent.highlighted || parent.hovered ? AppTheme.primaryContainer : "transparent" }
    }
    popup: Basic.Popup {
        objectName: control.objectName + "-popup"
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 2, 320)
        padding: 1
        margins: 8
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            Basic.ScrollIndicator.vertical: Basic.ScrollIndicator { }
        }
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 4 }
    }
}
