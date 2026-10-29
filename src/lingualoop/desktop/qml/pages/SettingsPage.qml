import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: shell
    property int section: 0
    spacing: 16
    RowLayout { visible: shell.section > 0
        MButton { objectName: "speechSettingsBack"; text: qsTr("‹ 本地语音模型"); variant: "text"; onClicked: shell.section = 0 }
        MLabel { text: qsTr("计算与加速"); role: "supporting" }
    }
    StackLayout {
        Layout.fillWidth: true; Layout.fillHeight: true
        currentIndex: shell.section > 0 ? 2 : workspace.settingsCategory === "local" ? 1 : 0
        ScrollView {
            id: overview
            objectName: "settingsOverview"
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: Math.min(overview.availableWidth,944); x: (overview.availableWidth-width)/2
                spacing: 24
                ColumnLayout {
                    visible: workspace.settingsCategory === "appearance"; Layout.fillWidth: true; spacing: 0
                    PreferenceChoice { label: qsTr("显示语言"); preferenceKey: "displayLanguage"; choices: [qsTr("简体中文"), qsTr("跟随系统（当前仅支持中文）")]; values: ["zh_CN", "system"] }
                    ThemeChoice { }
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
                    SettingsValue { label: qsTr("对话模型"); value: learningViewModel.modelServices.dialogue }
                    SettingsValue { label: qsTr("推理模型"); value: learningViewModel.modelServices.reasoning }
                    SettingsValue { label: qsTr("语音服务"); value: learningViewModel.speechStatus }
                    SettingsValue { label: qsTr("配置来源"); value: qsTr("连接配置从本地环境读取，修改后重启生效。"); divider: false }
                    MButton { text: qsTr("本地语音模型"); variant: "outlined"; onClicked: workspace.setCategory("local") }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "audio"; Layout.fillWidth: true; spacing: 0
                    SettingsRow { label: qsTr("麦克风"); MComboBox { Layout.preferredWidth: Math.min(300,shell.width-24); model: learningViewModel.inputDevices; textRole: "name"; Accessible.name: qsTr("麦克风"); onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, false) } }
                    SettingsRow { label: qsTr("播放设备"); divider: false; MComboBox { Layout.preferredWidth: Math.min(300,shell.width-24); model: learningViewModel.outputDevices; textRole: "name"; Accessible.name: qsTr("播放设备"); onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, true) } }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "data"; Layout.fillWidth: true; spacing: 0
                    SettingsValue { label: qsTr("本地数据"); value: qsTr("材料、已发送消息与复习项保存在本机。未发送草稿只保留在本次运行中；录音临时处理，结束会话后清理。") }
                    SettingsValue { label: qsTr("远程服务"); value: qsTr("使用远程模型时，相应文字或音频会发送到已配置服务。") }
                    SettingsRow { label: qsTr("当前工作区"); divider: false; MButton { text: qsTr("重置当前选择"); variant: "outlined"; enabled: !workspace.threadLocked; onClicked: learningViewModel.resetSession() } }
                }
            }
        }
        ColumnLayout {
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                MButton { objectName: "openSpeechCompute"; text: qsTr("计算与加速"); variant: "outlined"; onClicked: shell.section = 2 }
            }
            LocalSpeechLibrary { Layout.fillWidth: true; Layout.fillHeight: true; onOpenCompute: shell.section = 2 }
        }
        SpeechComputePage { }
    }
    Connections { target: workspace; function onChanged() { if (workspace.settingsCategory !== "local") shell.section = 0 } }
}
