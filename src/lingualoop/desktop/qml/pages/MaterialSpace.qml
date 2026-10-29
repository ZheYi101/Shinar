import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: page
    spacing: 16
    MaterialHeader { Layout.fillWidth: true }
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 0
            Repeater {
                model: workspace.threads
                ItemDelegate {
                    required property var modelData
                    required property int index
                    objectName: "openSession" + index
                    Layout.fillWidth: true; implicitHeight: 94
                    enabled: !workspace.threadLocked
                    background: Rectangle { color: parent.hovered ? AppTheme.surfaceContainerLow : "transparent"; Rectangle { width: parent.width; height: 1; color: AppTheme.outlineVariant; opacity: 0.55 } }
                    contentItem: ColumnLayout {
                        MLabel { text: modelData.title; font.family: AppTheme.readingFont; font.pixelSize: 18; maximumLineCount: 1; elide: Text.ElideRight }
                        MLabel { text: modelData.preview; role: "supporting"; maximumLineCount: 1; elide: Text.ElideRight }
                        MLabel { text: qsTr("%1 · %2 轮 · %3").arg(modelData.date).arg(modelData.turns).arg(modelData.active ? qsTr("进行中") : qsTr("已结束")); role: "supporting" }
                    }
                    onClicked: workspace.openThread(modelData.id)
                }
            }
            MLabel { visible: workspace.threads.length === 0; text: qsTr("还没有对话"); role: "supporting"; Layout.topMargin: 24 }
        }
    }
}
