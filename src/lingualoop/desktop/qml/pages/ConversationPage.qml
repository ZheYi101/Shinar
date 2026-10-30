import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

Item {
    id: page
    signal openMaterials()
    property real workspaceWidth: width
    readonly property var voice: learningViewModel.voiceController
    property bool followTail: true
    function scrollToTail() {
        if (followTail) conversation.contentItem.contentY = Math.max(0, conversation.contentItem.contentHeight - conversation.contentItem.height)
    }
    Timer { id: tailTimer; interval: 0; onTriggered: page.scrollToTail() }
    readonly property bool splitSource: workspaceWidth >= 1200
    RowLayout {
        anchors.fill: parent; spacing: 0
        SourceReader {
            visible: workspace.sourceOpen
            Layout.fillHeight: true; Layout.fillWidth: !page.splitSource
            Layout.preferredWidth: page.splitSource ? Math.max(360,page.width*0.49) : -1
            onBack: workspace.toggleSource()
        }
        ColumnLayout {
            visible: !workspace.sourceOpen || page.splitSource
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.leftMargin: page.width < 600 ? 12 : 24; Layout.rightMargin: page.width < 600 ? 12 : 24
            Layout.topMargin: 20
            spacing: 8
            MButton { visible: !learningViewModel.hasSession; text: qsTr("选择材料"); variant: "outlined"; onClicked: page.openMaterials() }
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
                                padding: modelData.role === "user" ? 18 : 0
                                MLabel { text: modelData.role === "user" ? qsTr("我") : qsTr("伙伴"); role: "supporting"; font.pixelSize: 12 }
                                MLabel { text: modelData.content; font.family: learningViewModel.preferences.targetLanguage === "japanese" ? AppTheme.japaneseReadingFont : AppTheme.readingFont; font.pixelSize: page.width < 600 ? 18 : 20; lineHeightMode: Text.FixedHeight; lineHeight: font.pixelSize * 1.6 }
                            }
                            MButton { visible: !!modelData.source; text: modelData.source ? modelData.source.label || qsTr("原文来源") : ""; variant: "text"; implicitHeight: 28; font.pixelSize: 12; Layout.maximumWidth: conversation.availableWidth; onClicked: workspace.previewMessage(modelData.id); contentItem: Text { text: parent.text; color: AppTheme.primary; font: parent.font; elide: Text.ElideRight } }
                            MLabel { visible: !!modelData.replyError; text: modelData.replyError || ""; color: AppTheme.error; role: "supporting" }
                            MButton { objectName: "retryReply-" + modelData.id; visible: !!modelData.canRetryReply; text: qsTr("重试本轮回复"); variant: "text"; enabled: !learningViewModel.busy; onClicked: voice.retryReply(modelData.turnId) }
                            MLabel { visible: !!modelData.speechError; text: modelData.speechError || ""; color: AppTheme.error; role: "supporting" }
                            MButton { objectName: "retrySpeech-" + modelData.id; visible: !!modelData.speechError; text: qsTr("重试朗读"); variant: "text"; enabled: !learningViewModel.busy; onClicked: voice.speakTurn(modelData.turnId || "legacy:" + modelData.id) }
                        }
                    }
                    MCard { visible: learningViewModel.pendingUserText.length > 0; color: AppTheme.surfaceContainerLow; padding: 14; MLabel { text: learningViewModel.pendingUserText; font.family: AppTheme.readingFont; font.pixelSize: 18 } }
                    MLabel { objectName: "streamingReplyText"; visible: voice.replyState === "generating"; text: learningViewModel.streamingText || "…"; font.family: AppTheme.readingFont; font.pixelSize: 18 }
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
                ColumnLayout {
                    visible: voice.transcriptionError.length > 0
                    Layout.fillWidth: true; spacing: 4
                    MLabel { text: voice.transcriptionError; color: AppTheme.error; role: "supporting"; Accessible.role: Accessible.AlertMessage }
                    MLabel { visible: voice.unsentTranscript.length > 0; text: voice.unsentTranscript; maximumLineCount: 4; elide: Text.ElideRight; role: "supporting" }
                    RowLayout {
                        MButton { objectName: "retryTranscriptionButton"; visible: voice.canRetryTranscription; text: qsTr("重试识别"); variant: "text"; enabled: !learningViewModel.busy; onClicked: learningViewModel.retryTranscription() }
                        MButton { visible: voice.unsentTranscript.length > 0; text: qsTr("复制转写"); variant: "text"; onClicked: voice.copyTranscript() }
                        MButton { objectName: "discardRecordingButton"; text: qsTr("丢弃录音"); variant: "text"; enabled: !learningViewModel.busy; onClicked: voice.discardRecording() }
                    }
                }
                Item {
                    Layout.fillWidth: true; Layout.preferredHeight: 28
                    RowLayout {
                        anchors.fill: parent
                        MLabel { objectName: "voiceStatusLabel"; text: voice.statusText; role: "supporting"; font.pixelSize: 12; maximumLineCount: 1; elide: Text.ElideRight }
                        MLabel { visible: voice.recognitionState === "recording"; text: qsTr("%1 秒").arg(learningViewModel.recordingSeconds); role: "supporting"; Layout.fillWidth: false; maximumLineCount: 1 }
                    }
                }
                Rectangle {
                    visible: workspace.hasSource
                    Layout.fillWidth: true
                    implicitHeight: 48
                    color: AppTheme.primaryContainer; radius: 4
                    RowLayout {
                        anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 4
                        MLabel { text: workspace.sourceLabel; maximumLineCount: 2; elide: Text.ElideRight; role: "supporting"; color: AppTheme.colorOnPrimaryContainer; font.pixelSize: 12 }
                        MIconButton { symbol: "close"; label: qsTr("清除指向"); onClicked: workspace.clearSource() }
                    }
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
                                placeholderText: qsTr("说说你的想法…")
                                text: learningViewModel.draft
                                onTextChanged: if (text !== learningViewModel.draft) learningViewModel.draft = text
                                onCursorPositionChanged: workspace.saveEditor(cursorPosition,conversation.contentItem.contentY)
                                Keys.onPressed: function(event) {
                                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier) && !messageField.inputMethodComposing) {
                                        if (learningViewModel.sessionActive && !learningViewModel.busy && text.trim()) { page.followTail = true; learningViewModel.sendMessage(text) }
                                        event.accepted = true
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 4
                            MButton { objectName: "recordButton"; visible: learningViewModel.voiceReady && learningViewModel.sessionActive; text: voice.recognitionState === "recording" ? qsTr("结束并发送") : qsTr("开始语音"); icon.source: "../assets/illustrated/mic.png"; enabled: !learningViewModel.busy || voice.recognitionState === "recording"; variant: "text"; onClicked: { page.followTail = true; if (voice.recognitionState === "recording") learningViewModel.stopRecording(); else learningViewModel.startRecording() } }
                            MIconButton { objectName: "cancelRecordingButton"; visible: voice.recognitionState === "recording"; symbol: "close"; label: qsTr("取消录音"); onClicked: learningViewModel.cancelRecording() }
                            Item { Layout.fillWidth: true }
                            MIconButton { objectName: "speakReplyButton"; visible: learningViewModel.canSpeak && !voice.canStopSpeech; symbol: "play_arrow"; label: qsTr("朗读回复"); enabled: !learningViewModel.busy; onClicked: learningViewModel.speakReply() }
                            MIconButton { objectName: "stopSpeechButton"; visible: voice.canStopSpeech; symbol: "stop"; label: qsTr("停止朗读"); onClicked: learningViewModel.stopPlayback() }
                            MButton { objectName: "sendMessageButton"; text: qsTr("发送 ↑"); enabled: learningViewModel.sessionActive && !learningViewModel.busy && learningViewModel.draft.trim().length > 0 && learningViewModel.voiceState !== "recording"; onClicked: { page.followTail = true; learningViewModel.sendMessage(learningViewModel.draft) } }
                        }
                    }
                }
            }
            RowLayout { visible: !learningViewModel.sessionActive && learningViewModel.hasSession; Layout.fillWidth: true
                MButton { text: qsTr("复盘"); variant: "text"; onClicked: workspace.navigate("review") }
                MButton { text: qsTr("+ 新对话"); variant: "text"; enabled: !workspace.threadLocked; onClicked: { workspace.browseMaterial(learningViewModel.selectedMaterialId); workspace.newThreadPage() } }
            }
            Item { Layout.preferredHeight: 10 }
        }
    }
    Connections {
        target: workspace
        function onEditorRestoreRequested(cursor, scroll) { page.followTail = false; Qt.callLater(function() { messageField.cursorPosition = Math.min(cursor,messageField.length); conversation.contentItem.contentY = scroll; page.followTail = conversation.contentItem.contentY >= conversation.contentItem.contentHeight - conversation.contentItem.height - 24 }) }
        function onFocusComposerRequested() { Qt.callLater(function() { messageField.forceActiveFocus() }) }
    }
    Connections {
        target: conversation.contentItem
        function onContentHeightChanged() { tailTimer.restart() }
        function onHeightChanged() { tailTimer.restart() }
        function onContentYChanged() {
            if (conversation.contentItem.dragging || conversation.ScrollBar.vertical.pressed) page.followTail = conversation.contentItem.contentY >= conversation.contentItem.contentHeight - conversation.contentItem.height - 24
            if (page.visible) workspace.saveEditor(messageField.cursorPosition,conversation.contentItem.contentY)
        }
    }
    Connections {
        target: learningViewModel
        function onMessagesChanged() { tailTimer.restart() }
        function onUiChanged() { if(learningViewModel.streamingText.length) tailTimer.restart() }
    }
}
