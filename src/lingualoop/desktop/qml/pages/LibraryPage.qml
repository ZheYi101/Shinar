import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        Item { Layout.fillWidth: true }
        MTextField { id: search; Layout.preferredWidth: 220; Layout.minimumWidth: 100; Layout.fillWidth: true; Layout.maximumWidth: 220; placeholderText: "查找材料" }
        MButton { text: "+ 导入材料"; onClicked: workspace.navigate("import") }
    }
    ScrollView {
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentWidth: availableWidth
        ColumnLayout {
            width: parent.width; spacing: 0
            RowLayout { Layout.fillWidth: true; Layout.preferredHeight: 32
                MLabel { text: "材料"; role: "supporting"; Layout.fillWidth: true }
                MLabel { visible: parent.width > 540; text: "语言与类型"; role: "supporting"; Layout.preferredWidth: 150; Layout.fillWidth: false }
                MLabel { text: "已读范围"; role: "supporting"; Layout.preferredWidth: 100; Layout.fillWidth: false }
                MLabel { visible: parent.width > 420; text: "对话"; role: "supporting"; Layout.preferredWidth: 60; Layout.fillWidth: false }
            }
            Repeater {
                model: workspace.materials
                ItemDelegate {
                    required property var modelData
                    Layout.fillWidth: true; implicitHeight: 52
                    visible: modelData.title.toLowerCase().indexOf(search.text.toLowerCase()) >= 0
                    Accessible.name: modelData.title
                    background: Rectangle { color: parent.hovered ? AppTheme.surfaceContainerLow : "transparent"; Rectangle { width: parent.width; height: 1; color: AppTheme.outlineVariant; opacity: 0.55 } }
                    contentItem: RowLayout {
                        MLabel { text: modelData.title; font.family: AppTheme.readingFont; font.pixelSize: 17; elide: Text.ElideRight; maximumLineCount: 1 }
                        MLabel { visible: parent.width > 520; text: modelData.language + " · " + modelData.type; role: "supporting"; Layout.preferredWidth: 150; Layout.fillWidth: false }
                        MLabel { text: modelData.range; role: "supporting"; Layout.preferredWidth: 100; Layout.fillWidth: false }
                        MLabel { visible: parent.width > 400; text: modelData.threads.length; role: "supporting"; Layout.preferredWidth: 44; Layout.fillWidth: false }
                    }
                    onClicked: workspace.browseMaterial(modelData.id)
                }
            }
            MLabel { visible: workspace.materials.length === 0; text: "还没有材料"; role: "supporting"; Layout.topMargin: 36 }
        }
    }
}
