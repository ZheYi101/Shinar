import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import "../design"
import "../components"

Item {
    id: page
    signal navigate(int page)
    property bool editing: false
    property bool showSource: false
    property bool showStructure: false
    property bool optionsExpanded: false
    property bool partialReading: false
    property int approximateProgress: 50
    property bool showProgressPreview: false
    ColumnLayout {
        anchors.fill: parent
        spacing: AppTheme.sectionGap
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                MLabel { text: "材料"; role: "headline" }
                MLabel { visible: page.width > 500; text: "带着你读过的故事，随意聊聊。"; role: "supporting" }
            }
            MButton { text: "导入"; objectName: "importButton"; enabled: !learningViewModel.busy; onClicked: fileDialog.open() }
            MButton { text: "粘贴"; variant: "tonal"; onClicked: page.editing = !page.editing }
        }
        ScrollView {
            id: materialScroll
            objectName: "materialScroll"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: materialScroll.availableWidth
                spacing: AppTheme.sectionGap
                MCard {
                    visible: learningViewModel.materials.length === 0 && !page.editing
                    MLabel { text: "最近在读什么？"; role: "title" }
                    MLabel { text: "导入小说、文章或字幕。读了一部分也没关系，我们只聊你已经看过的内容。"; role: "supporting" }
                    MButton { text: "粘贴一段内容"; variant: "tonal"; onClicked: page.editing = true }
                }
                MCard {
                    visible: page.editing
                    MLabel { text: "粘贴内容"; role: "title" }
                    MTextField { id: titleField; objectName: "materialTitleInput"; Layout.fillWidth: true; placeholderText: "材料标题" }
                    MTextArea { id: materialField; objectName: "materialTextInput"; Layout.fillWidth: true; Layout.preferredHeight: 160; placeholderText: "原文或字幕" }
                    MLabel { text: "先保存到本机。导入不会调用 AI 生成题库。"; role: "supporting" }
                    MButton {
                        text: learningViewModel.busy ? "正在保存…" : "保存材料"
                        objectName: "saveMaterialButton"
                        enabled: !learningViewModel.busy && titleField.text.trim().length > 0 && materialField.text.trim().length > 0
                        onClicked: learningViewModel.loadMaterial(titleField.text, materialField.text,
                            learningViewModel.preferences.targetLanguage, learningViewModel.preferences.targetLanguage,
                            learningViewModel.preferences.nativeLanguage, learningViewModel.preferences.difficulty)
                    }
                }
                Flow {
                    Layout.fillWidth: true; spacing: AppTheme.gapSmall
                    Repeater {
                        model: learningViewModel.materials
                        MChip {
                            required property var modelData
                            text: modelData.title
                            checked: learningViewModel.selectedMaterialId === modelData.id
                            enabled: !learningViewModel.busy
                            onClicked: learningViewModel.selectMaterial(modelData.id)
                            Accessible.name: "选择材料 " + modelData.title
                        }
                    }
                }
                MCard {
                    visible: learningViewModel.hasMaterial
                    MLabel { text: learningViewModel.materialTitle; role: "title" }
                    MLabel { text: learningViewModel.readingScopeLabel; role: "supporting"; objectName: "readingScopeLabel" }
                    MLabel { text: "读到哪里了？确认后会使用推理服务整理已读内容，可先聊天。后文不进入参考。"; role: "supporting" }
                    Flow {
                        Layout.fillWidth: true; spacing: AppTheme.gapSmall
                        MButton { text: "已经读完"; objectName: "readWholeMaterialButton"; variant: "tonal"; enabled: !learningViewModel.busy && !learningViewModel.sessionActive; onClicked: learningViewModel.confirmReadingPercent(100) }
                        MButton { text: page.partialReading ? "收起阅读进度" : "还在读，设置位置"; objectName: "partialReadingButton"; variant: "text"; enabled: !learningViewModel.sessionActive; onClicked: page.partialReading = !page.partialReading }
                    }
                    ColumnLayout {
                        visible: page.partialReading
                        Layout.fillWidth: true
                        MLabel { text: "粘贴已读到的最后一句，精确定位"; role: "label" }
                        MTextField { id: lastPassage; objectName: "readingPassageInput"; Layout.fillWidth: true; placeholderText: "原文中唯一的一句，至少 8 个字符" }
                        MButton { text: "确认读到这句"; objectName: "confirmReadingPassageButton"; variant: "tonal"; enabled: !learningViewModel.busy && !learningViewModel.sessionActive && lastPassage.text.trim().length >= 8; onClicked: learningViewModel.confirmReadingPassage(lastPassage.text) }
                        MLabel { text: "也可用大致进度定位。请核对下面的实际末尾，确认自己已经读过。"; role: "supporting" }
                        RowLayout {
                            Layout.fillWidth: true
                            SpinBox { objectName: "readingPercentInput"; from: 1; to: 99; value: page.approximateProgress; implicitHeight: 48; editable: true; onValueModified: { page.approximateProgress = value; page.showProgressPreview = false } Accessible.name: "已读原文百分比" }
                            MLabel { text: "% · 按原文长度，向前取整到段落"; role: "supporting"; Layout.fillWidth: true }
                        }
                        MButton { text: "核对这个位置"; objectName: "previewReadingPositionButton"; variant: "text"; onClicked: page.showProgressPreview = true }
                        MLabel { visible: page.showProgressPreview; objectName: "readingPreviewText"; text: learningViewModel.hasMaterial ? learningViewModel.readingPreview(page.approximateProgress) : ""; role: "supporting"; maximumLineCount: 8; elide: Text.ElideLeft }
                        MButton { visible: page.showProgressPreview; text: "确认读过以上内容"; objectName: "confirmReadingPercentButton"; variant: "tonal"; enabled: !learningViewModel.busy && !learningViewModel.sessionActive; onClicked: learningViewModel.confirmReadingPercent(page.approximateProgress) }
                    }
                    MLabel { text: learningViewModel.materialPreparation; role: "supporting"; objectName: "materialPreparationLabel" }
                    MButton { visible: learningViewModel.canResumeMaterialPreparation; text: "继续基础整理"; objectName: "resumeMaterialPreparationButton"; variant: "tonal"; enabled: !learningViewModel.busy; onClicked: learningViewModel.resumeMaterialPreparation() }
                    MLabel { text: "不用选题。先说说你的感受，聊着聊着再找方向。"; role: "body" }
                    MTextField {
                        visible: page.optionsExpanded
                        objectName: "customTopicInput"
                        Layout.fillWidth: true; placeholderText: "想先聊什么？（可留空，将放入草稿）"
                        text: learningViewModel.customTopic
                        onTextEdited: learningViewModel.customTopic = text
                    }
                    Flow {
                        visible: page.optionsExpanded
                        Layout.fillWidth: true; spacing: AppTheme.gapSmall
                        MChip { text: "自由聊天"; checked: learningViewModel.practiceMode === "discussion"; onClicked: learningViewModel.practiceMode = "discussion" }
                        MChip { text: "语境 roleplay"; checked: learningViewModel.practiceMode === "roleplay"; onClicked: learningViewModel.practiceMode = "roleplay" }
                    }
                    MTextField { visible: page.optionsExpanded && learningViewModel.practiceMode === "roleplay"; Layout.fillWidth: true; placeholderText: "描述你和 AI 各自的角色"; text: learningViewModel.roleDescription; onTextEdited: learningViewModel.roleDescription = text }
                    Flow {
                        Layout.fillWidth: true; spacing: AppTheme.gapSmall
                        MButton {
                            text: learningViewModel.sessionActive ? "继续聊天" : "聊聊这份材料"
                            objectName: "startDiscussionButton"
                            enabled: !learningViewModel.busy && (learningViewModel.sessionActive || learningViewModel.readingScopeConfirmed)
                            onClicked: { if (learningViewModel.sessionActive) page.navigate(1); else learningViewModel.startPractice() }
                        }
                        MButton { text: page.optionsExpanded ? "收起选项" : "开场想法与模式"; objectName: "discussionOptionsButton"; variant: "text"; onClicked: page.optionsExpanded = !page.optionsExpanded }
                    }
                }
                MCard {
                    visible: learningViewModel.hasMaterial && learningViewModel.readingScopeConfirmed
                    MButton { text: page.showStructure ? "收起已有参考" : "查看已有参考"; objectName: "expandMaterialSummaryButton"; variant: "text"; onClicked: page.showStructure = !page.showStructure }
                    ColumnLayout {
                        visible: page.showStructure; Layout.fillWidth: true
                        MLabel { objectName: "materialSummaryText"; text: learningViewModel.analysisSummary; maximumLineCount: page.showStructure ? 2147483647 : 7; elide: Text.ElideRight }
                        Repeater { model: page.showStructure ? learningViewModel.analysisOutline : []; MLabel { required property string modelData; text: "· " + modelData; role: "supporting" } }
                        Repeater { model: page.showStructure ? learningViewModel.analysisCharacters : []; MLabel { required property var modelData; text: modelData.name + "：" + modelData.description; role: "supporting" } }
                        MLabel { visible: learningViewModel.topics.length > 0; text: "已有话题资料继续作为内部参考，聊天不需要按顺序进行。"; role: "supporting" }
                    }
                    MButton { text: page.showSource ? "收起已读原文" : "查看已读原文"; variant: "text"; onClicked: page.showSource = !page.showSource }
                    MLabel { visible: page.showSource; text: learningViewModel.materialNormalizedContent; font.family: AppTheme.japaneseFont }
                }
                Item { Layout.preferredHeight: 16 }
            }
        }
    }
    Dialogs.FileDialog {
        id: fileDialog
        objectName: "materialFileDialog"
        title: "导入沉浸材料"
        nameFilters: ["沉浸材料 (*.txt *.srt *.vtt *.md *.markdown *.docx *.epub *.xlsx *.mp4 *.mkv *.webm *.mov *.avi)"]
        onAccepted: learningViewModel.importMaterial(selectedFile.toString(), "",
            learningViewModel.preferences.targetLanguage, learningViewModel.preferences.targetLanguage,
            learningViewModel.preferences.nativeLanguage, learningViewModel.preferences.difficulty, "live_chat")
    }
}
