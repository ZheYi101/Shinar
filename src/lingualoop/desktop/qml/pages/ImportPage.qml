import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import "../design"
import "../components"

ColumnLayout {
    id: page
    spacing: 28
    ColumnLayout {
        Layout.fillWidth: true; Layout.maximumWidth: 880; Layout.alignment: Qt.AlignHCenter
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            MIconButton { symbol: "arrow_back"; label: qsTr("返回材料库"); onClicked: workspace.navigate("library") }
            MButton { objectName: "fileImportTab"; text: qsTr("本地文件"); variant: workspace.importMode === "file" ? "tonal" : "text"; onClicked: workspace.setImportMode("file") }
            MButton { objectName: "pasteImportTab"; text: qsTr("粘贴内容"); variant: workspace.importMode === "paste" ? "tonal" : "text"; onClicked: workspace.setImportMode("paste") }
            Item { Layout.fillWidth: true }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: AppTheme.outlineVariant }
    }
    ColumnLayout {
        Layout.fillWidth: true; Layout.maximumWidth: 880; Layout.alignment: Qt.AlignHCenter
        spacing: 24
        Rectangle {
            objectName: "importDropArea"
            visible: workspace.importMode === "file"
            Layout.fillWidth: true
            Layout.preferredHeight: workspace.importFile ? 100 : page.width < 600 ? 220 : 280
            color: drop.containsDrag ? AppTheme.primaryContainer : AppTheme.surfaceContainerLow
            radius: 5; border.color: AppTheme.outlineVariant
            RowLayout {
                anchors.centerIn: parent; width: Math.min(parent.width-32, implicitWidth); spacing: 16
                MLabel { visible: workspace.importFile.length > 0; text: workspace.importFile; maximumLineCount: 2; elide: Text.ElideMiddle }
                MButton { text: workspace.inspecting ? qsTr("正在读取…") : workspace.importFile ? qsTr("重新选择") : qsTr("选择文件"); variant: "outlined"; enabled: !workspace.inspecting; onClicked: filePicker.open() }
                MLabel { visible: !workspace.importFile; text: qsTr("或拖入文件"); role: "supporting"; Layout.fillWidth: false }
            }
            DropArea { id: drop; anchors.fill: parent; onDropped: function(drop) { if(drop.hasUrls && drop.urls.length) workspace.inspectFile(drop.urls[0]) } }
        }
        ColumnLayout {
            visible: workspace.importMode === "paste" || workspace.importFile.length > 0
            Layout.fillWidth: true; spacing: 8
            MLabel { text: qsTr("材料名称（可留空）"); role: "label" }
            MTextField { objectName: "importTitleInput"; Layout.fillWidth: true; placeholderText: qsTr("名称"); text: workspace.importTitle; onTextEdited: workspace.importTitle = text; Accessible.name: qsTr("材料名称") }
        }
        ScrollView {
            visible: workspace.importMode === "paste"
            Layout.fillWidth: true; Layout.preferredHeight: Math.max(140, Math.min(360, page.height-260))
            contentWidth: availableWidth; clip: true
            MTextArea { objectName: "importTextInput"; width: parent.width; implicitHeight: Math.max(140,contentHeight+20); placeholderText: qsTr("粘贴原文"); text: workspace.importText; onTextChanged: if (text !== workspace.importText) workspace.importText = text; Accessible.name: qsTr("材料正文") }
        }
        RowLayout {
            Layout.fillWidth: true
            MButton { objectName: "commitImportButton"; text: qsTr("继续"); enabled: !learningViewModel.busy && !workspace.inspecting; onClicked: workspace.commitImport() }
            Item { Layout.fillWidth: true }
            MLabel { text: qsTr("材料语言"); Layout.fillWidth: false }
            MComboBox { Layout.preferredWidth: page.width < 600 ? 100 : 140; model: [qsTr("英语"), qsTr("日语"), qsTr("中文"), qsTr("法语"), qsTr("德语"), qsTr("西班牙语")]; property var values: ["english", "japanese", "chinese", "french", "germany", "spanish"]; currentIndex: Math.max(0, values.indexOf(workspace.importLanguage)); onActivated: workspace.importLanguage = values[currentIndex]; Accessible.name: qsTr("材料语言") }
        }
    }
    Item { Layout.fillHeight: true }
    Dialogs.FileDialog { id: filePicker; nameFilters: [qsTr("材料 (*.txt *.md *.markdown *.epub *.docx *.xlsx *.srt *.vtt *.mp4 *.mkv *.webm *.mov *.avi)")]; onAccepted: workspace.inspectFile(selectedFile.toString()) }
}
