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
    readonly property var call: voice.continuous
    readonly property var readiness: voice.readiness
    onVisibleChanged: readiness.setPageVisible(visible)
    Component.onCompleted: readiness.setPageVisible(visible)
    Component.onDestruction: readiness.setPageVisible(false)
    property bool followTail: true
    property real sourceFraction: 0.49
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
            Layout.preferredWidth: page.splitSource ? Math.max(360,page.width*page.sourceFraction) : -1
            onBack: workspace.toggleSource()
        }
        Rectangle {
            objectName: "sourceSplitHandle"
            visible: workspace.sourceOpen && page.splitSource
            Layout.preferredWidth: 10; Layout.fillHeight: true
            color: splitMouse.containsMouse || splitMouse.pressed ? AppTheme.outlineVariant : "transparent"
            MouseArea {
                id: splitMouse
                objectName: "sourceSplitMouse"
                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.SplitHCursor
                preventStealing: true
                onPositionChanged: function(mouse) {
                    if (splitMouse.pressed) {
                        const point = mapToItem(page, mouse.x, mouse.y)
                        page.sourceFraction = Math.max(360 / page.width, Math.min(1 - 360 / page.width, point.x / page.width))
                    }
                }
            }
            Accessible.name: qsTr("调整原文与对话宽度")
        }
        ColumnLayout {
            visible: !workspace.sourceOpen || page.splitSource
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.leftMargin: page.width < 600 ? 12 : 24; Layout.rightMargin: page.width < 600 ? 12 : 24
            Layout.topMargin: 28
            spacing: 8
            MButton { visible: !learningViewModel.hasSession; text: qsTr("选择材料"); variant: "outlined"; onClicked: page.openMaterials() }
            ScrollView {
                id: conversation
                objectName: "practiceScroll"
                Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: Math.min(conversation.availableWidth,760)
                    x: (conversation.availableWidth-width)/2
                    spacing: 16
                    Repeater {
                        model: learningViewModel.messages
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 4
                            ConversationMessage { message: modelData }
                            MButton { visible: !!modelData.source; text: modelData.source ? modelData.source.label || qsTr("原文来源") : ""; variant: "text"; implicitHeight: 28; font.pixelSize: 12; Layout.maximumWidth: conversation.availableWidth; onClicked: workspace.previewMessage(modelData.id); contentItem: Text { text: parent.text; color: AppTheme.primary; font: parent.font; elide: Text.ElideRight } }
                            MLabel { visible: !!modelData.replyError; text: modelData.replyError || ""; color: AppTheme.error; role: "supporting" }
                            MLabel { visible: !!modelData.replyNotice; text: modelData.replyNotice || ""; role: "supporting" }
                            MButton { objectName: "retryReply-" + modelData.id; visible: !!modelData.canRetryReply; text: qsTr("重试本轮回复"); variant: "text"; enabled: voice.canSendText; onClicked: voice.retryReply(modelData.turnId) }
                            MLabel { visible: !!modelData.speechError; text: modelData.speechError || ""; color: AppTheme.error; role: "supporting" }
                            MButton { visible: !!modelData.speechSetupRequired; text: qsTr("设置此语言的语音模型"); variant: "text"; onClicked: { speechLibrary.setFilter(learningViewModel.speechLanguage, "conversation"); workspace.setCategory("local"); workspace.navigate("settings") } }
                            MButton { objectName: "retrySpeech-" + modelData.id; visible: !!modelData.speechError; text: qsTr("重试朗读"); variant: "text"; enabled: voice.canSendText; onClicked: voice.speakTurn(modelData.turnId || "legacy:" + modelData.id) }
                        }
                    }
                    MCard { visible: learningViewModel.pendingUserText.length > 0; Layout.maximumWidth: 560; Layout.alignment: Qt.AlignRight; color: AppTheme.surfaceContainerLow; padding: 14; MLabel { text: learningViewModel.pendingUserText; font.pixelSize: 16 } }
                    MLabel { objectName: "streamingReplyText"; visible: voice.replyState === "generating"; text: learningViewModel.streamingText || "…"; font.family: learningViewModel.preferences.targetLanguage === "japanese" ? AppTheme.japaneseFont : AppTheme.uiFont; font.pixelSize: 16 }
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
                    objectName: "voiceReadinessPanel"
                    visible: learningViewModel.sessionActive && !voice.active
                    Layout.fillWidth: true; spacing: 2
                    Flow {
                        Layout.fillWidth: true; spacing: 12
                        Repeater {
                            model: readiness.checks
                            MLabel {
                                required property var modelData
                                objectName: "voiceReadiness-" + modelData.id
                                text: qsTr("%1：%2").arg(modelData.label).arg(modelData.text)
                                width: Math.min(implicitWidth, parent.width)
                                color: modelData.state === "error" ? AppTheme.error : AppTheme.colorOnSurfaceVariant
                                role: "supporting"; font.pixelSize: 12
                            }
                        }
                    }
                    MLabel { text: qsTr("进入页面会短暂检查麦克风，检查音频不保存、不发送；点击语音对话后开始监听。"); role: "supporting"; font.pixelSize: 11 }
                    Repeater {
                        model: readiness.checks
                        MLabel {
                            required property var modelData
                            visible: modelData.error.length > 0
                            text: modelData.error; color: AppTheme.error; role: "supporting"; font.pixelSize: 12
                        }
                    }
                    Flow {
                        Layout.fillWidth: true; spacing: 6
                        MButton { objectName: "retryVoiceReadiness"; text: qsTr("重新检查"); variant: "text"; font.pixelSize: 12; enabled: readiness.canCheck; onClicked: readiness.retry() }
                        MButton { objectName: "readinessModelSettings"; visible: readiness.needsModelSettings; text: qsTr("设置此语言的语音模型"); variant: "text"; font.pixelSize: 12; onClicked: { speechLibrary.setFilter(learningViewModel.speechLanguage, "conversation"); workspace.setCategory("local"); workspace.navigate("settings") } }
                        MButton { objectName: "readinessAudioSettings"; visible: readiness.needsAudioSettings; text: qsTr("检查音频设备"); variant: "text"; font.pixelSize: 12; onClicked: { workspace.setCategory("audio"); workspace.navigate("settings") } }
                        MButton { visible: readiness.canOpenMicrophoneSettings; text: qsTr("系统麦克风权限"); variant: "text"; font.pixelSize: 12; onClicked: readiness.openMicrophoneSettings() }
                    }
                }
                MLabel { visible: call.errorText.length > 0; text: call.errorText; color: AppTheme.error; role: "supporting"; Accessible.role: Accessible.AlertMessage }
                MButton { objectName: "openSpeechModelSettings"; visible: call.canOpenModelSettings; text: qsTr("设置此语言的语音模型"); variant: "text"; onClicked: { speechLibrary.setFilter(learningViewModel.speechLanguage, "conversation"); workspace.setCategory("local"); workspace.navigate("settings") } }
                MButton { objectName: "openMicrophoneSettingsButton"; visible: call.canOpenMicrophoneSettings; text: qsTr("打开系统麦克风设置"); variant: "text"; onClicked: call.openMicrophoneSettings() }
                MLabel { visible: call.active && call.noticeText.length > 0; text: call.noticeText; role: "supporting"; font.pixelSize: 12 }
                Flow {
                    visible: call.hasPendingInput; Layout.fillWidth: true; spacing: 6
                    MButton { objectName: "sendPausedInputButton"; visible: call.canSendPausedInput; text: qsTr("发送已说内容"); variant: "text"; onClicked: call.sendPausedInput() }
                    MButton { objectName: "retryContinuousInput"; visible: call.canRetryInput; text: qsTr("重试识别"); variant: "text"; onClicked: call.retryInput() }
                    MButton { objectName: "discardContinuousInput"; text: qsTr("丢弃未发送语音"); variant: "text"; onClicked: call.discardInput() }
                }
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
                    visible: call.active || voice.recognitionState === "recording" || voice.recognitionState === "transcribing"
                    Layout.fillWidth: true; Layout.preferredHeight: call.active ? 64 : 28
                    Rectangle { anchors.fill: parent; visible: call.active; radius: 5; color: AppTheme.primaryContainer; border.color: AppTheme.outlineVariant }
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 6; spacing: 4
                        RowLayout {
                            Layout.fillWidth: true; Layout.preferredHeight: 20
                            MLabel { objectName: "voiceStatusLabel"; text: voice.statusText; role: "supporting"; font.pixelSize: 12; maximumLineCount: 1; elide: Text.ElideRight; color: call.active ? AppTheme.colorOnPrimaryContainer : AppTheme.colorOnSurfaceVariant }
                            MLabel { visible: voice.recognitionState === "recording"; text: qsTr("%1 秒").arg(learningViewModel.recordingSeconds); role: "supporting"; Layout.fillWidth: false; maximumLineCount: 1 }
                            MLabel { visible: call.active && call.attributionText.length > 0; text: call.attributionText; Layout.fillWidth: false; Layout.maximumWidth: 150; font.pixelSize: 11; maximumLineCount: 1; elide: Text.ElideRight; role: "supporting" }
                        }
                        RowLayout {
                            objectName: "continuousVoiceControls"
                            visible: learningViewModel.voiceReady && learningViewModel.sessionActive
                            Layout.fillWidth: true; Layout.preferredHeight: 36; spacing: 4
                            MButton { objectName: "muteMicrophoneButton"; visible: call.active; text: call.muted ? qsTr("继续说") : qsTr("暂停麦克风"); variant: "text"; implicitWidth: 110; font.pixelSize: 12; enabled: call.connectionState === "active" && !call.microphoneBusy; onClicked: { if (call.muted) call.resumeMicrophone(); else call.muteMicrophone() } }
                            MButton { objectName: "stopReplyButton"; visible: call.active; text: qsTr("停止回复"); variant: "text"; enabled: call.replyState === "generating" || call.outputState !== "idle"; onClicked: call.stopReply() }
                            Item { Layout.fillWidth: true }
                        }
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
                    implicitHeight: Math.min(220,Math.max(112,messageField.contentHeight+68))
                    color: AppTheme.dark ? AppTheme.surfaceContainer : "#FBF8F0"; radius: 16
                    border.color: messageField.activeFocus ? AppTheme.primary : AppTheme.outlineVariant
                    Behavior on border.color { ColorAnimation { duration: AppTheme.motionFast } }
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 8; spacing: 4
                        ScrollView {
                            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth
                            MTextArea {
                                id: messageField; objectName: "messageInput"
                                width: parent.width; implicitHeight: Math.max(48,contentHeight+12)
                                background: null; padding: 6
                                placeholderText: qsTr("聊聊你的想法…")
                                text: learningViewModel.draft
                                onTextChanged: if (text !== learningViewModel.draft) learningViewModel.draft = text
                                onCursorPositionChanged: workspace.saveEditor(cursorPosition,conversation.contentItem.contentY)
                                Keys.onPressed: function(event) {
                                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier) && !messageField.inputMethodComposing) {
                                        if (learningViewModel.sessionActive && voice.canSendText && text.trim()) { page.followTail = true; learningViewModel.sendMessage(text) }
                                        event.accepted = true
                                    }
                                }
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 4
                            MButton { objectName: "continuousVoiceButton"; visible: learningViewModel.voiceReady && learningViewModel.sessionActive; text: call.active ? qsTr("结束语音") : qsTr("语音对话"); variant: call.active ? "tonal" : "text"; font.pixelSize: 12; enabled: call.active || (!learningViewModel.busy && !readiness.busy); onClicked: { page.followTail = true; if (call.active) call.stop(); else call.start() } }
                            MButton { objectName: "recordButton"; visible: learningViewModel.voiceReady && learningViewModel.sessionActive && !call.active; text: voice.recognitionState === "recording" ? qsTr("结束并发送") : qsTr("分轮录音"); font.pixelSize: 12; enabled: !learningViewModel.busy || voice.recognitionState === "recording"; variant: "text"; onClicked: { page.followTail = true; if (voice.recognitionState === "recording") learningViewModel.stopRecording(); else learningViewModel.startRecording() } }
                            MIconButton { objectName: "cancelRecordingButton"; visible: voice.recognitionState === "recording"; symbol: "close"; label: qsTr("取消录音"); onClicked: learningViewModel.cancelRecording() }
                            Item { Layout.fillWidth: true }
                            MIconButton { objectName: "speakReplyButton"; visible: learningViewModel.canSpeak && !voice.canStopSpeech; symbol: "play_arrow"; label: qsTr("朗读回复"); enabled: voice.canSendText; onClicked: learningViewModel.speakReply() }
                            MIconButton { objectName: "stopSpeechButton"; visible: voice.canStopSpeech; symbol: "stop"; label: qsTr("停止朗读"); onClicked: learningViewModel.stopPlayback() }
                            MIconButton { objectName: "sendMessageButton"; symbol: "arrow_up"; label: qsTr("发送 · Enter，Shift+Enter 换行"); filled: true; enabled: learningViewModel.sessionActive && voice.canSendText && learningViewModel.draft.trim().length > 0 && learningViewModel.voiceState !== "recording"; onClicked: { page.followTail = true; learningViewModel.sendMessage(learningViewModel.draft) } }
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
