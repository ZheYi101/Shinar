import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

Item {
    id: page
    signal openMaterials()
    property bool splitSource: width + (workspace.collapsed ? 56 : 208) >= 1200
    RowLayout {
        anchors.fill: parent; spacing: 0
        SourceReader {
            visible: workspace.sourceOpen
            Layout.fillHeight: true; Layout.fillWidth: !page.splitSource
            Layout.preferredWidth: page.splitSource ? Math.max(360,page.width*0.46) : -1
            onBack: workspace.toggleSource()
        }
        ColumnLayout {
            visible: !workspace.sourceOpen || page.splitSource
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.leftMargin: page.width < 600 ? 12 : 24; Layout.rightMargin: page.width < 600 ? 12 : 24
            spacing: 8
            RowLayout {
                Layout.fillWidth: true; Layout.preferredHeight: 36
                Item { Layout.fillWidth: true }
                MButton { objectName: "openHistoryButton"; text: "对话列表"; variant: "text"; onClicked: workspace.browseMaterial(learningViewModel.selectedMaterialId) }
                MButton { text: "原文"; variant: "text"; enabled: learningViewModel.hasSession; onClicked: workspace.toggleSource() }
                MIconButton { objectName: "conversationMenuButton"; symbol: "more_horiz"; label: "对话操作"; onClicked: actions.open() }
            }
            MButton { visible: !learningViewModel.hasSession; text: "选择材料"; variant: "outlined"; onClicked: page.openMaterials() }
            ScrollView {
                id: conversation
                objectName: "practiceScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: Math.min(conversation.availableWidth,760)
                    x: (conversation.availableWidth-width)/2
                    spacing: 24
                    Repeater {
                        model: learningViewModel.messages
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 4
                            MCard {
                                Layout.fillWidth: true
                                color: modelData.role === "user" ? AppTheme.surfaceContainerLow : "transparent"
                                padding: modelData.role === "user" ? 14 : 0
                                MLabel { text: modelData.content; font.family: learningViewModel.preferences.targetLanguage === "japanese" ? AppTheme.japaneseReadingFont : AppTheme.readingFont; font.pixelSize: 18; lineHeight: 1.6 }
                            }
                            MButton { visible: !!modelData.source; text: modelData.source ? modelData.source.label || "原文来源" : ""; variant: "text"; implicitHeight: 28; font.pixelSize: 12; Layout.maximumWidth: conversation.availableWidth; onClicked: workspace.previewMessage(modelData.id); contentItem: Text { text: parent.text; color: AppTheme.primary; font: parent.font; elide: Text.ElideRight } }
                        }
                    }
                    MCard { visible: learningViewModel.pendingUserText.length > 0; color: AppTheme.surfaceContainerLow; padding: 14; MLabel { text: learningViewModel.pendingUserText; font.family: AppTheme.readingFont; font.pixelSize: 18 } }
                    MLabel { objectName: "streamingReplyText"; visible: learningViewModel.pendingUserText.length > 0; text: learningViewModel.streamingText || "…"; font.family: AppTheme.readingFont; font.pixelSize: 18 }
                    Flow { Layout.fillWidth: true; spacing: 8
                        Repeater { model: learningViewModel.suggestedDirections
                            MButton { required property string modelData; required property int index; objectName: "suggestedDirection" + index; text: modelData; variant: "text"; implicitWidth: Math.min(page.width-32,320); implicitHeight: Math.max(36,contentItem.implicitHeight+12); contentItem: Text { text: parent.text; color: AppTheme.primary; font: parent.font; wrapMode: Text.Wrap } onClicked: learningViewModel.useDirection(modelData) }
                        }
                    }
                }
            }
            ColumnLayout {
                objectName: "conversationComposer"
                visible: learningViewModel.sessionActive || learningViewModel.canSpeak
                Layout.fillWidth: true; Layout.maximumWidth: 760; Layout.alignment: Qt.AlignHCenter
                spacing: 6
                RowLayout {
                    visible: workspace.hasSource
                    Layout.fillWidth: true
                    MLabel { text: workspace.sourceLabel; maximumLineCount: 1; elide: Text.ElideRight; role: "supporting" }
                    MIconButton { symbol: "close"; label: "清除指向"; onClicked: workspace.clearSource() }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.min(200,Math.max(108,messageField.contentHeight+54))
                    color: AppTheme.dark ? AppTheme.surfaceContainer : "#FBF8F0"; radius: 5
                    border.color: messageField.activeFocus ? AppTheme.primary : AppTheme.outline
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 6; spacing: 0
                        ScrollView {
                            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                            MTextArea {
                                id: messageField; objectName: "messageInput"
                                width: parent.width; implicitHeight: Math.max(48,contentHeight+12)
                                background: null; padding: 6
                                placeholderText: "说说你的想法…"
                                text: learningViewModel.draft
                                enabled: learningViewModel.voiceState !== "recording"
                                onTextChanged: if (text !== learningViewModel.draft) learningViewModel.draft = text
                                onCursorPositionChanged: workspace.saveEditor(cursorPosition,conversation.contentItem.contentY)
                                Keys.onPressed: function(event) {
                                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                                        if (learningViewModel.sessionActive && !learningViewModel.busy && text.trim()) learningViewModel.sendMessage(text)
                                        event.accepted = true
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 4
                            MButton { objectName: "recordButton"; visible: learningViewModel.voiceReady && learningViewModel.sessionActive; text: learningViewModel.voiceState === "recording" ? "结束录音" : "开始语音"; icon.source: "../assets/illustrated/mic.png"; enabled: !learningViewModel.busy; variant: "text"; onClicked: learningViewModel.voiceState === "recording" ? learningViewModel.stopRecording() : learningViewModel.startRecording() }
                            MButton { visible: learningViewModel.voiceState === "recording"; text: "取消"; variant: "text"; onClicked: learningViewModel.cancelRecording() }
                            MButton { visible: learningViewModel.canRetryTranscription; text: "重试识别"; variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.retryTranscription() }
                            MIconButton { visible: learningViewModel.canSpeak && learningViewModel.voiceState !== "playing"; symbol: "play_arrow"; label: "朗读回复"; enabled: !learningViewModel.busy; onClicked: learningViewModel.speakReply() }
                            MIconButton { visible: learningViewModel.voiceState === "playing"; symbol: "stop"; label: "停止播放"; onClicked: learningViewModel.stopPlayback() }
                            MLabel { text: learningViewModel.voiceState === "recording" ? learningViewModel.recordingSeconds + " 秒" : ""; role: "supporting"; maximumLineCount: 1 }
                            MButton { objectName: "sendMessageButton"; text: "发送 ↑"; enabled: learningViewModel.sessionActive && !learningViewModel.busy && learningViewModel.draft.trim().length > 0 && learningViewModel.voiceState !== "recording"; onClicked: learningViewModel.sendMessage(learningViewModel.draft) }
                        }
                    }
                }
            }
            RowLayout { visible: !learningViewModel.sessionActive && learningViewModel.hasSession; Layout.fillWidth: true
                MButton { text: "复盘"; variant: "text"; onClicked: workspace.navigate("review") }
                MButton { text: "+ 新对话"; variant: "text"; enabled: !workspace.threadLocked; onClicked: { workspace.browseMaterial(learningViewModel.selectedMaterialId); workspace.newThreadPage() } }
            }
            Item { Layout.preferredHeight: 10 }
        }
    }
    Menu {
        id: actions; x: Math.max(0,page.width-width-16); y: 36
        MenuItem { objectName: "finishDiscussionButton"; text: "结束并复盘"; enabled: learningViewModel.sessionActive && !workspace.threadLocked; onTriggered: learningViewModel.finishPractice() }
        MenuItem { text: "复盘"; enabled: learningViewModel.hasSession && !learningViewModel.sessionActive; onTriggered: workspace.navigate("review") }
        MenuItem { text: "本轮信息"; onTriggered: info.open() }
    }
    Popup {
        id: info; x: Math.max(0,page.width-width-16); y: 36; width: Math.min(380,page.width-24)
        background: Rectangle { color: AppTheme.surface; border.color: AppTheme.outlineVariant; radius: 5 }
        contentItem: ColumnLayout { MLabel { text: learningViewModel.responseTiming; role: "supporting" } MLabel { text: learningViewModel.preparationStatus; role: "supporting" } MLabel { text: learningViewModel.speechStatus; role: "supporting" } }
    }
    Connections {
        target: workspace
        function onEditorRestoreRequested(cursor, scroll) { Qt.callLater(function() { messageField.cursorPosition = Math.min(cursor,messageField.length); conversation.contentItem.contentY = scroll }) }
        function onFocusComposerRequested() { Qt.callLater(function() { messageField.forceActiveFocus() }) }
    }
    Connections { target: conversation.contentItem; function onContentYChanged() { if (page.visible) workspace.saveEditor(messageField.cursorPosition,conversation.contentItem.contentY) } }
    Connections {
        target: learningViewModel
        function onMessagesChanged() { Qt.callLater(function() { conversation.contentItem.contentY = Math.max(0,conversation.contentItem.contentHeight-conversation.height) }) }
        function onUiChanged() { if(learningViewModel.streamingText.length) Qt.callLater(function() { conversation.contentItem.contentY = Math.max(0,conversation.contentItem.contentHeight-conversation.height) }) }
    }
}
