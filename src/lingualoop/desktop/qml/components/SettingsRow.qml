import QtQuick
import QtQuick.Layouts
import "../design"

Item {
    id: root
    default property alias controls: trailing.data
    property string label: ""
    property bool divider: true
    property bool inlineControl: false
    readonly property bool compact: width < 520 && !inlineControl
    Layout.fillWidth: true
    implicitHeight: Math.max(68, content.implicitHeight + 28)
    GridLayout {
        id: content
        width: root.width
        anchors.verticalCenter: parent.verticalCenter
        columns: root.compact ? 1 : 2
        columnSpacing: 24
        rowSpacing: 12
        MLabel { text: root.label; role: "label"; Layout.minimumWidth: 100 }
        RowLayout {
            id: trailing
            Layout.alignment: Qt.AlignRight
            Layout.fillWidth: root.compact
            spacing: 8
        }
    }
    Rectangle { visible: root.divider; anchors.bottom: parent.bottom; width: parent.width; height: 1; color: AppTheme.outlineVariant; opacity: 0.45 }
}
