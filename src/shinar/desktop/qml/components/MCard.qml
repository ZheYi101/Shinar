import QtQuick
import QtQuick.Layouts
import "../design"

Rectangle {
    id: card
    default property alias body: column.data
    property int padding: AppTheme.gapLarge
    property bool outlined: false
    implicitWidth: 240
    implicitHeight: column.implicitHeight + padding * 2
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    color: AppTheme.surfaceContainerLow
    radius: AppTheme.cardRadius
    border.width: outlined ? 1 : 0
    border.color: AppTheme.outlineVariant
    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: card.padding
        spacing: AppTheme.gapMedium
    }
}
