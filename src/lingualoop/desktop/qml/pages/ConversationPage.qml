import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

Item {
    id: page
    readonly property bool shortWindow: height < 520
    signal openContext()
    signal openMaterials()
    ColumnLayout {
        anchors.fill: parent
        spacing: AppTheme.gapMedium
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                MLabel { text: learningViewModel.topicTitle; role: "title"; maximumLineCount: page.shortWindow ? 1 : 2; elide: Text.ElideRight }
                MLabel { visible: !page.shortWindow; text: learningViewModel.materialTitle || "从最近读过的材料聊起"; role: "supporting"; maximumLineCount: 1; elide: Text.ElideRight }
            }
            MIconButton { symbol: "info"; label: "查看本次语境"; onClicked: page.openContext() }
            MButton { objectName: "openHistoryButton"; text: "历史对话"; variant: "tonal"; enabled: !learningViewModel.busy; onClicked: historyDialog.open() }
        }
        MButton { visible: !learningViewModel.hasSession; text: "选择一份材料"; variant: "tonal"; onClicked: page.openMaterials() }
        RowLayout {
            visible: learningViewModel.hasSession && !learningViewModel.sessionActive
            Layout.fillWidth: true
            MLabel { text: "这次对话已结束，内容已保存在本机。"; role: "supporting" }
            MButton { text: "再聊一次"; variant: "text"; onClicked: page.openMaterials() }
        }
        ScrollView {
            id: conversation
            objectName: "practiceScroll"
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: conversation.availableWidth
                spacing: AppTheme.gapLarge
                Repeater {
                    model: learningViewModel.messages
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Item { visible: modelData.role === "user"; Layout.fillWidth: true }
                        MCard {
                            Layout.fillWidth: false
                            Layout.preferredWidth: Math.max(160, Math.min(conversation.availableWidth * 0.9, 720))
                            color: modelData.role === "user" ? AppTheme.primaryContainer : AppTheme.surfaceContainerLow
                            MLabel { text: modelData.role === "user" ? "我" : "AI"; role: "label"; color: AppTheme.colorOnSurfaceVariant }
                            MLabel { text: modelData.content; font.family: learningViewModel.preferences.targetLanguage === "japanese" ? AppTheme.japaneseFont : AppTheme.uiFont }
                        }
                        Item { visible: modelData.role !== "user"; Layout.fillWidth: true }
                    }
                }
                MCard {
                    visible: learningViewModel.pendingUserText.length > 0
                    Layout.preferredWidth: Math.max(160, Math.min(conversation.availableWidth * 0.9, 720))
                    Layout.fillWidth: false; Layout.alignment: Qt.AlignRight
                    color: AppTheme.primaryContainer
                    MLabel { text: "我"; role: "label" }
                    MLabel { text: learningViewModel.pendingUserText; font.family: AppTheme.japaneseFont }
                }
                MCard {
                    visible: learningViewModel.pendingUserText.length > 0
                    objectName: "streamingReplyCard"
                    Layout.preferredWidth: Math.max(160, Math.min(conversation.availableWidth * 0.9, 720))
                    Layout.fillWidth: false
                    MLabel { text: "AI"; role: "label" }
                    MLabel { objectName: "streamingReplyText"; text: learningViewModel.streamingText || "正在回复…"; font.family: AppTheme.japaneseFont }
                }
                ColumnLayout {
                    visible: learningViewModel.sessionActive && learningViewModel.suggestedDirections.length > 0
                    Layout.fillWidth: true
                    MLabel { text: "顺着刚才的话，也可以聊聊…"; role: "supporting" }
                    Flow {
                        Layout.fillWidth: true; spacing: AppTheme.gapSmall
                        Repeater {
                            model: learningViewModel.suggestedDirections
                            MButton {
                                required property string modelData
                                required property int index
                                objectName: "suggestedDirection" + index
                                text: modelData; variant: "tonal"
                                implicitWidth: Math.min(page.width - 16, 360)
                        implicitHeight: Math.max(AppTheme.touchTarget, contentItem.implicitHeight + 16)
                        contentItem: Text { text: modelData; font: parent.font; color: parent.contentColor; textFormat: Text.PlainText; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                enabled: !learningViewModel.busy
                                onClicked: learningViewModel.useDirection(modelData)
                                Accessible.description: "放入草稿，可编辑后发送；也可以继续聊自己的想法"
                            }
                        }
                    }
                }
            }
        }
        MCard {
            objectName: "conversationComposer"
            visible: learningViewModel.sessionActive || learningViewModel.canSpeak
            MLabel {
                visible: learningViewModel.sessionActive || learningViewModel.voiceState === "playing" || learningViewModel.voiceState === "synthesizing"
                role: "supporting"
                text: learningViewModel.voiceState === "recording" ? "● 正在录音 · " + learningViewModel.recordingSeconds + " / 60 秒" :
                      learningViewModel.voiceState === "transcribing" ? "正在识别发言…" :
                      learningViewModel.voiceState === "synthesizing" ? "正在合成 AI 语音…" :
                      learningViewModel.voiceState === "playing" ? "正在播放 AI 生成语音" :
                      learningViewModel.busy ? learningViewModel.status : "写下你的想法。Ctrl+Enter 发送。"
            }
            ScrollView {
                visible: learningViewModel.sessionActive
                Layout.fillWidth: true; Layout.preferredHeight: page.shortWindow ? 56 : 104
                contentWidth: availableWidth
                MTextArea {
                    id: messageField
                    objectName: "messageInput"
                    width: parent.width
                    placeholderText: "你想说什么？"
                    text: learningViewModel.draft
                    enabled: !learningViewModel.busy && learningViewModel.voiceState !== "recording"
                    onTextChanged: if (text !== learningViewModel.draft) learningViewModel.draft = text
                    Keys.onPressed: function(event) {
                        if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ControlModifier)) {
                            if (learningViewModel.sessionActive && !learningViewModel.busy && text.trim().length > 0) learningViewModel.sendMessage(text)
                            event.accepted = true
                        }
                    }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: AppTheme.gapSmall
                MButton {
                    objectName: "recordButton"
                    visible: learningViewModel.voiceReady && learningViewModel.sessionActive
                    text: learningViewModel.voiceState === "recording" ? "结束录音" : "开始说话"
                    icon.source: "../assets/" + (learningViewModel.voiceState === "recording" ? "stop" : "mic") + ".svg"
                    enabled: learningViewModel.sessionActive && !learningViewModel.busy
                    variant: learningViewModel.draft.trim().length > 0 ? "tonal" : "filled"
                    onClicked: learningViewModel.voiceState === "recording" ? learningViewModel.stopRecording() : learningViewModel.startRecording()
                }
                MButton {
                    text: "发送"; objectName: "sendMessageButton"
                    visible: learningViewModel.sessionActive
                    variant: learningViewModel.draft.trim().length > 0 ? "filled" : "tonal"
                    enabled: learningViewModel.sessionActive && !learningViewModel.busy && learningViewModel.draft.trim().length > 0 && learningViewModel.voiceState !== "recording"
                    onClicked: learningViewModel.sendMessage(learningViewModel.draft)
                }
                MButton { text: "重新录音"; variant: "text"; visible: learningViewModel.canRetryTranscription && learningViewModel.draft.length > 0; enabled: !learningViewModel.busy; onClicked: learningViewModel.rerecord() }
                MButton { text: "取消录音"; variant: "text"; visible: learningViewModel.voiceState === "recording"; onClicked: learningViewModel.cancelRecording() }
                MIconButton { symbol: "stop"; label: "停止播放"; visible: learningViewModel.voiceState === "playing"; onClicked: learningViewModel.stopPlayback() }
                MIconButton { symbol: "play_arrow"; label: "朗读或重播 AI 回复"; visible: learningViewModel.canSpeak && learningViewModel.voiceState !== "playing"; enabled: !learningViewModel.busy; onClicked: learningViewModel.speakReply() }
                MButton { text: "重试识别"; variant: "text"; visible: learningViewModel.canRetryTranscription && learningViewModel.voiceState === "error"; enabled: !learningViewModel.busy; onClicked: learningViewModel.retryTranscription() }
            }
            MLabel {
                visible: !page.shortWindow && learningViewModel.sessionActive
                // Background status must not move the send/record hit targets.
                Layout.preferredHeight: 40
                Layout.minimumHeight: 40
                Layout.maximumHeight: 40
                maximumLineCount: 2
                elide: Text.ElideRight
                text: learningViewModel.responseTiming
                role: "supporting"
                objectName: "backgroundPreparationLabel"
            }
        }
        MButton { text: "结束并复盘"; objectName: "finishDiscussionButton"; visible: learningViewModel.sessionActive; variant: "text"; enabled: learningViewModel.sessionActive && !learningViewModel.busy && learningViewModel.voiceState !== "recording"; onClicked: learningViewModel.finishPractice() }
    }
    Connections {
        target: learningViewModel
        function onMessagesChanged() {
            Qt.callLater(function() {
                const flick = conversation.contentItem
                if (flick && flick.contentHeight !== undefined)
                    flick.contentY = Math.max(0, flick.contentHeight - flick.height)
            })
        }
        function onUiChanged() {
            if (learningViewModel.streamingText.length > 0) Qt.callLater(function() {
                const flick = conversation.contentItem
                if (flick && flick.contentHeight !== undefined) flick.contentY = Math.max(0, flick.contentHeight - flick.height)
            })
        }
    }
    MDialog {
        id: historyDialog
        objectName: "sessionHistoryDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(page.width + 16, 600)
        height: Math.min(page.height + 16, learningViewModel.sessionHistory.length > 0 ? 620 : 260)
        title: "本地对话历史 · " + learningViewModel.sessionHistory.length
        footer: DialogButtonBox {
            MButton { text: "关闭"; variant: "text"; onClicked: historyDialog.close() }
        }
        contentItem: ScrollView {
            id: historyScroll
            objectName: "historyScroll"
            contentWidth: availableWidth
            ColumnLayout {
                width: historyScroll.availableWidth
                spacing: AppTheme.gapMedium
                MLabel { visible: learningViewModel.sessionHistory.length === 0; text: "还没有对话。选择一个材料话题开始，发送的消息会自动保存。"; role: "supporting" }
                Repeater {
                    model: learningViewModel.sessionHistory
                    MCard {
                        id: historyCard
                        required property var modelData
                        required property int index
                        color: modelData.selected ? AppTheme.primaryContainer : AppTheme.surfaceContainerLow
                        MLabel { text: modelData.date + " · " + modelData.status + " · " + modelData.turns + " 轮"; role: "supporting" }
                        MLabel { text: historyCard.modelData.title; role: "title"; maximumLineCount: 2; elide: Text.ElideRight }
                        MLabel { text: modelData.preview; maximumLineCount: 3; elide: Text.ElideRight }
                        MButton { objectName: "openSession" + historyCard.index; text: historyCard.modelData.selected ? "当前对话" : "打开对话"; variant: "text"; onClicked: { const sessionId = historyCard.modelData.id; historyDialog.close(); learningViewModel.selectSession(sessionId) } }
                    }
                }
            }
        }
    }
}
