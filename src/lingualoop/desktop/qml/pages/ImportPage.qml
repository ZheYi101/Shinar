import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import "../design"
import "../components"

ColumnLayout {
    id: page
    spacing: 24
    RowLayout {
        MButton { text: "‹ 返回"; variant: "text"; onClicked: workspace.navigate("library") }
        Item { Layout.fillWidth: true }
        MButton { text: "本地文件"; variant: workspace.importMode === "file" ? "tonal" : "text"; onClicked: workspace.setImportMode("file") }
        MButton { text: "粘贴内容"; variant: workspace.importMode === "paste" ? "tonal" : "text"; onClicked: workspace.setImportMode("paste") }
    }
    ColumnLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; Layout.maximumWidth: 860; Layout.alignment: Qt.AlignHCenter
        spacing: 24
        MTextField { Layout.fillWidth: true; placeholderText: "材料名称"; text: workspace.importTitle; onTextEdited: workspace.importTitle = text; Accessible.name: "材料名称" }
        Rectangle {
            visible: workspace.importMode === "file"
            Layout.fillWidth: true; Layout.fillHeight: true
            color: drop.containsDrag ? AppTheme.primaryContainer : AppTheme.surfaceContainerLow
            radius: 5; border.color: AppTheme.outlineVariant
            ColumnLayout {
                anchors.centerIn: parent; spacing: 20
                StyleIcon { name: "book"; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 46; Layout.preferredHeight: 46 }
                MLabel { text: workspace.inspecting ? "正在读取…" : workspace.importFile || "拖入材料文件"; Layout.maximumWidth: Math.max(100, page.width-80); maximumLineCount: 2; elide: Text.ElideMiddle; horizontalAlignment: Text.AlignHCenter }
                MButton { text: workspace.importFile ? "重新选择" : "选择文件"; variant: "outlined"; Layout.alignment: Qt.AlignHCenter; onClicked: filePicker.open() }
            }
            DropArea { id: drop; anchors.fill: parent; onDropped: function(drop) { if(drop.hasUrls && drop.urls.length) workspace.inspectFile(drop.urls[0]) } }
        }
        MTextArea { visible: workspace.importMode === "paste"; Layout.fillWidth: true; Layout.fillHeight: true; placeholderText: "粘贴原文"; text: workspace.importText; onTextChanged: if (text !== workspace.importText) workspace.importText = text; Accessible.name: "材料正文" }
        RowLayout {
            Layout.fillWidth: true
            MLabel { text: "材料语言"; Layout.fillWidth: false }
            ComboBox { model: ["英语", "日语", "中文", "法语", "德语", "西班牙语"]; property var values: ["english", "japanese", "chinese", "french", "germany", "spanish"]; currentIndex: Math.max(0, values.indexOf(workspace.importLanguage)); onActivated: workspace.importLanguage = values[currentIndex]; implicitHeight: 38; Accessible.name: "材料语言" }
            Item { Layout.fillWidth: true }
            MButton { text: "继续"; enabled: !learningViewModel.busy && !workspace.inspecting; onClicked: workspace.commitImport() }
        }
    }
    Dialogs.FileDialog { id: filePicker; nameFilters: ["材料 (*.txt *.md *.markdown *.epub *.docx *.xlsx *.srt *.vtt *.mp4 *.mkv *.webm *.mov *.avi)"]; onAccepted: workspace.inspectFile(selectedFile.toString()) }
}
