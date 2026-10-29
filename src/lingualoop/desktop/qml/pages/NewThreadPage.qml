import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ScrollView {
    id: page
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: Math.min(page.availableWidth, 760)
        x: (page.availableWidth-width)/2
        spacing: 20
        RowLayout {
            Layout.fillWidth: true
            MButton { text: qsTr("‹ 返回"); variant: "text"; onClicked: workspace.navigate("material") }
            MLabel { text: workspace.material.title || ""; maximumLineCount: 1; elide: Text.ElideRight }
            MLabel { text: workspace.material.range || ""; role: "supporting"; Layout.fillWidth: false }
        }
        MLabel { text: qsTr("开场想法（可留空）"); role: "label" }
        ScrollView {
            Layout.fillWidth: true; Layout.preferredHeight: 140
            contentWidth: availableWidth; clip: true
            MTextArea {
                objectName: "customTopicInput"
                width: parent.width
                implicitHeight: Math.max(140, contentHeight+20)
                placeholderText: qsTr("想从哪一处聊起？")
                text: workspace.openingDraft
                onTextChanged: if (text !== workspace.openingDraft) workspace.openingDraft = text
            }
        }
        RowLayout {
            Layout.fillWidth: true
            MButton { text: qsTr("自然讨论"); variant: learningViewModel.practiceMode === "discussion" ? "tonal" : "outlined"; onClicked: learningViewModel.practiceMode = "discussion" }
            MButton { text: qsTr("角色扮演"); variant: learningViewModel.practiceMode === "roleplay" ? "tonal" : "outlined"; onClicked: learningViewModel.practiceMode = "roleplay" }
            Item { Layout.fillWidth: true }
            MButton { objectName: "startDiscussionButton"; text: qsTr("开始对话"); enabled: !workspace.threadLocked; onClicked: workspace.startThread() }
        }
        MLabel { visible: learningViewModel.practiceMode === "roleplay"; text: qsTr("角色与情境"); role: "label" }
        MTextField { visible: learningViewModel.practiceMode === "roleplay"; Layout.fillWidth: true; placeholderText: qsTr("描述希望扮演的角色"); text: learningViewModel.roleDescription; onTextEdited: learningViewModel.roleDescription = text }
        Item { Layout.preferredHeight: 20 }
    }
}
