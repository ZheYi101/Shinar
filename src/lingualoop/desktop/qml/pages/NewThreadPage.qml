import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    spacing: 24
    RowLayout { MButton { text: "‹ 返回"; variant: "text"; onClicked: workspace.navigate("material") } MLabel { text: workspace.material.title || ""; font.family: AppTheme.readingFont; maximumLineCount: 1; elide: Text.ElideRight } }
    Item { Layout.fillHeight: true }
    ColumnLayout {
        Layout.fillWidth: true; Layout.maximumWidth: 700; Layout.alignment: Qt.AlignHCenter
        spacing: 24
        MTextArea { objectName: "customTopicInput"; Layout.fillWidth: true; implicitHeight: 140; placeholderText: "想聊什么？（可留空）"; text: workspace.openingDraft; onTextChanged: if (text !== workspace.openingDraft) workspace.openingDraft = text }
        RowLayout {
            ComboBox { model: ["自然讨论", "角色扮演"]; currentIndex: learningViewModel.practiceMode === "roleplay" ? 1 : 0; onActivated: learningViewModel.practiceMode = currentIndex === 1 ? "roleplay" : "discussion"; Accessible.name: "对话方式"; implicitHeight: 38 }
            Item { Layout.fillWidth: true }
            MButton { objectName: "startDiscussionButton"; text: "开始对话"; enabled: !workspace.threadLocked; onClicked: workspace.startThread() }
        }
        MTextField { visible: learningViewModel.practiceMode === "roleplay"; Layout.fillWidth: true; placeholderText: "角色与情境"; text: learningViewModel.roleDescription; onTextEdited: learningViewModel.roleDescription = text }
    }
    Item { Layout.fillHeight: true }
}
