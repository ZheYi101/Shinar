import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: shell
    property int section: 0
    spacing: 8
    RowLayout { visible: shell.section > 0
        MButton { objectName: "speechSettingsBack"; text: qsTr("‹ 本地语音模型"); variant: "text"; onClicked: shell.section = 0 }
    }
    StackLayout {
        Layout.fillWidth: true; Layout.fillHeight: true
        currentIndex: shell.section > 0 ? shell.section : workspace.settingsCategory === "local" ? 1 : 0
        ScrollView {
            id: overview
            objectName: "settingsOverview"
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: Math.min(overview.availableWidth,720); x: (overview.availableWidth-width)/2
                spacing: 24
                ColumnLayout {
                    visible: workspace.settingsCategory === "appearance"; Layout.fillWidth: true; spacing: 0
                    PreferenceChoice { label: qsTr("显示语言"); preferenceKey: "displayLanguage"; choices: [qsTr("简体中文"), qsTr("跟随系统（当前仅支持中文）")]; values: ["zh_CN", "system"] }
                    ThemeChoice { }
                    PreferenceChoice { label: qsTr("关闭主窗口时"); preferenceKey: "closeBehavior"; choices: [qsTr("每次询问"), qsTr("后台运行"), qsTr("退出程序")]; values: ["ask", "background", "quit"] }
                    MLabel { Layout.fillWidth: true; visible: !desktopLifecycle.backgroundAvailable; text: qsTr("当前系统托盘不可用，关闭窗口将退出程序。"); role: "supporting" }
                    SettingsRow { label: qsTr("减少动效"); divider: false; inlineControl: true; MSwitch { objectName: "reducedMotionSwitch"; Accessible.name: qsTr("减少动效"); checked: learningViewModel.preferences.reducedMotion; onToggled: learningViewModel.preferences.setValue("reducedMotion", checked) } }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "learning"; Layout.fillWidth: true; spacing: 0
                    PreferenceChoice { label: qsTr("目标语言"); preferenceKey: "targetLanguage"; choices: [qsTr("日语"), qsTr("英语"), qsTr("中文"), qsTr("法语"), qsTr("德语"), qsTr("西班牙语")]; values: ["japanese", "english", "chinese", "french", "germany", "spanish"] }
                    PreferenceChoice { label: qsTr("母语"); preferenceKey: "nativeLanguage"; choices: [qsTr("中文"), qsTr("英语"), qsTr("日语"), qsTr("法语"), qsTr("德语"), qsTr("西班牙语")]; values: ["chinese", "english", "japanese", "french", "germany", "spanish"] }
                    PreferenceChoice { label: qsTr("难度"); preferenceKey: "difficulty"; choices: [qsTr("暂不确定"), "A1", "A2", "B1", "B2", "C1", "C2"]; values: ["unknown", "A1", "A2", "B1", "B2", "C1", "C2"] }
                    PreferenceChoice { label: qsTr("反馈时机"); preferenceKey: "feedbackTiming"; choices: [qsTr("结束后集中反馈"), qsTr("本轮不纠错")]; values: ["end", "off"] }
                    PreferenceChoice { label: qsTr("纠错强度"); preferenceKey: "correctionIntensity"; choices: [qsTr("轻量"), qsTr("适中"), qsTr("详细")]; values: ["low", "medium", "high"] }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "services"; Layout.fillWidth: true; spacing: 0
                    AIServiceSettings { controller: aiServices; Layout.bottomMargin: 20 }
                    SettingsValue { label: qsTr("对话模型"); value: learningViewModel.modelServices.dialogue }
                    SettingsValue { label: qsTr("推理模型"); value: learningViewModel.modelServices.reasoning }
                    SettingsValue { label: qsTr("语音服务"); value: learningViewModel.speechStatus }
                    MButton { text: qsTr("本地语音模型"); variant: "outlined"; onClicked: workspace.setCategory("local") }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "audio"; Layout.fillWidth: true; spacing: 0
                    ContinuousVoiceSetup { controller: learningViewModel.voiceController.continuous; Layout.bottomMargin: 16 }
                    SettingsRow { label: qsTr("发言停顿"); MComboBox { objectName: "voicePauseChoice"; model: [qsTr("650 毫秒 · 普通停顿"), qsTr("1000 毫秒 · 较长停顿")]; currentIndex: learningViewModel.preferences.voicePauseMs === "1000" ? 1 : 0; enabled: !learningViewModel.voiceController.continuous.active; onActivated: learningViewModel.preferences.setValue("voicePauseMs", currentIndex === 1 ? "1000" : "650") } }
                    SettingsRow { label: qsTr("自动朗读回复"); inlineControl: true; MSwitch { objectName: "autoReadRepliesSwitch"; Accessible.name: qsTr("自动朗读回复"); checked: learningViewModel.preferences.autoReadReplies; onToggled: learningViewModel.preferences.setValue("autoReadReplies", checked) } }
                    SettingsRow { label: qsTr("麦克风"); MComboBox { objectName: "inputDeviceChoice"; Layout.preferredWidth: Math.min(300,shell.width-24); model: learningViewModel.inputDevices; textRole: "name"; currentIndex: model.findIndex(d => d.id === learningViewModel.selectedInputDeviceId); Accessible.name: qsTr("麦克风"); onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, false) } }
                    SettingsRow { label: qsTr("播放设备"); divider: false; MComboBox { objectName: "outputDeviceChoice"; Layout.preferredWidth: Math.min(300,shell.width-24); model: learningViewModel.outputDevices; textRole: "name"; currentIndex: model.findIndex(d => d.id === learningViewModel.selectedOutputDeviceId); Accessible.name: qsTr("播放设备"); onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, true) } }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "data"; Layout.fillWidth: true; spacing: 0
                    SettingsValue { label: qsTr("本地数据"); value: qsTr("材料、已发送消息与复习项保存在本机。未发送草稿只保留在本次运行中；录音临时处理，结束会话后清理。") }
                    SettingsValue { label: qsTr("远程服务"); value: qsTr("使用远程模型时，相应文字或音频会发送到已配置服务。") }
                    SettingsRow { label: qsTr("模型文件与运行环境"); MButton { objectName: "openDataSpeechStorage"; text: qsTr("存储管理"); variant: "outlined"; onClicked: { workspace.setCategory("local"); shell.section = 3 } } }
                    SettingsRow { label: qsTr("当前工作区"); divider: false; MButton { text: qsTr("重置当前选择"); variant: "outlined"; enabled: !workspace.threadLocked; onClicked: learningViewModel.resetSession() } }
                }
            }
        }
        LocalSpeechLibrary { Layout.fillWidth: true; Layout.fillHeight: true; onOpenCompute: shell.section = 2; onOpenStorage: shell.section = 3 }
        SpeechComputePage { }
        SpeechStoragePage { Layout.fillWidth: true; Layout.fillHeight: true }
    }
    Connections { target: workspace; function onChanged() { if (workspace.settingsCategory !== "local") shell.section = 0 } }
}
