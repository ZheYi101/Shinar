import QtQuick
import QtQuick.Layouts
import "../design"

Item {
    default property alias body: content.data
    implicitWidth: 280
    implicitHeight: content.implicitHeight + 78
    Layout.fillWidth: true
    Layout.minimumWidth: 0

    Image {
        anchors.fill: parent
        visible: !AppTheme.dark
        source: Qt.resolvedUrl("../assets/decorative/paper-slip.svg")
        fillMode: Image.Stretch
        Accessible.ignored: true
    }
    Rectangle {
        anchors.fill: parent
        visible: AppTheme.dark
        color: AppTheme.surfaceContainerLow
        border.color: AppTheme.outlineVariant
        radius: 2
    }
    PaperTexture { anchors.fill: parent; anchors.margins: 4; quiet: true }
    Image {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: -6
        width: 62; height: 18
        rotation: -6
        source: Qt.resolvedUrl("../assets/decorative/paper-tape.svg")
        opacity: AppTheme.dark ? 0.35 : 0.64
        Accessible.ignored: true
    }
    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 18
        spacing: 12
    }
    InkDecoration {
        anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.rightMargin: 16; anchors.bottomMargin: 12
        width: 44; height: 44
    }
}
