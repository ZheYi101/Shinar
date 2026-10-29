import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: page
    spacing: 16
    RowLayout {
        Layout.fillWidth: true
        MLabel { text: workspace.material.title || ""; font.family: AppTheme.readingFont; font.pixelSize: 23; maximumLineCount: 1; elide: Text.ElideRight }
        MButton { text: workspace.material.range || "已读范围"; variant: "text"; onClicked: workspace.openScope() }
        MButton { text: "+ 新对话"; enabled: !workspace.threadLocked; onClicked: workspace.newThreadPage() }
    }
    RowLayout {
        MButton { text: "对话"; variant: "tonal" }
        MButton { text: "已读范围"; variant: "text"; onClicked: workspace.openScope() }
    }
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
                        MLabel { text: modelData.date + " · " + modelData.turns + " 轮 · " + (modelData.active ? "进行中" : "已结束"); role: "supporting" }
                    }
                    onClicked: workspace.openThread(modelData.id)
                }
            }
            MLabel { visible: workspace.threads.length === 0; text: "还没有对话"; role: "supporting"; Layout.topMargin: 24 }
        }
    }
}
