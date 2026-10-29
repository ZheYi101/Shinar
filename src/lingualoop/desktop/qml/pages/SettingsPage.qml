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
        MButton { objectName: "speechSettingsBack"; text: "‹ 本地语音模型"; variant: "text"; onClicked: shell.section = 0 }
        MLabel { text: "计算与加速"; role: "supporting" }
    }
    StackLayout {
        Layout.fillWidth: true; Layout.fillHeight: true
        currentIndex: shell.section > 0 ? 2 : workspace.settingsCategory === "local" ? 1 : 0
        ScrollView {
            id: overview
            objectName: "settingsOverview"
            contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: Math.min(overview.availableWidth,920); x: (overview.availableWidth-width)/2
                spacing: 24
                ColumnLayout {
                    visible: workspace.settingsCategory === "appearance"; Layout.fillWidth: true; spacing: 20
                    PreferenceChoice { label: "主题"; preferenceKey: "themeMode"; choices: ["跟随系统", "浅色", "深色"]; values: ["system", "light", "dark"] }
                    Switch { text: "减少动效"; checked: learningViewModel.preferences.reducedMotion; onToggled: learningViewModel.preferences.setValue("reducedMotion", checked) }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "learning"; Layout.fillWidth: true; spacing: 20
                    PreferenceChoice { label: "目标语言"; preferenceKey: "targetLanguage"; choices: ["日语", "英语", "中文", "法语", "德语", "西班牙语"]; values: ["japanese", "english", "chinese", "french", "germany", "spanish"] }
                    PreferenceChoice { label: "母语"; preferenceKey: "nativeLanguage"; choices: ["中文", "英语", "日语", "法语", "德语", "西班牙语"]; values: ["chinese", "english", "japanese", "french", "germany", "spanish"] }
                    PreferenceChoice { label: "难度"; preferenceKey: "difficulty"; choices: ["暂不确定", "A1", "A2", "B1", "B2", "C1", "C2"]; values: ["unknown", "A1", "A2", "B1", "B2", "C1", "C2"] }
                    PreferenceChoice { label: "反馈时机"; preferenceKey: "feedbackTiming"; choices: ["结束后集中反馈", "本轮不纠错"]; values: ["end", "off"] }
                    PreferenceChoice { label: "纠错强度"; preferenceKey: "correctionIntensity"; choices: ["轻量", "适中", "详细"]; values: ["low", "medium", "high"] }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "services"; Layout.fillWidth: true; spacing: 24
                    MLabel { text: "对话模型"; role: "label" }
                    MLabel { text: learningViewModel.modelServices.dialogue }
                    MLabel { text: "推理模型"; role: "label" }
                    MLabel { text: learningViewModel.modelServices.reasoning }
                    MLabel { text: "语音服务"; role: "label" }
                    MLabel { text: learningViewModel.speechStatus }
                    MLabel { text: "连接配置从本地环境读取，修改后重启生效。"; role: "supporting" }
                    MButton { text: "本地语音模型"; variant: "outlined"; onClicked: workspace.setCategory("local") }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "audio"; Layout.fillWidth: true; spacing: 24
                    MLabel { text: "麦克风"; role: "label" }
                    ComboBox { Layout.fillWidth: true; model: learningViewModel.inputDevices; textRole: "name"; Accessible.name: "麦克风"; onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, false) }
                    MLabel { text: "播放设备"; role: "label" }
                    ComboBox { Layout.fillWidth: true; model: learningViewModel.outputDevices; textRole: "name"; Accessible.name: "播放设备"; onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, true) }
                }
                ColumnLayout {
                    visible: workspace.settingsCategory === "data"; Layout.fillWidth: true; spacing: 24
                    MLabel { text: "材料、已发送消息与复习项保存在本机。未发送草稿只保留在本次运行中；录音临时处理，结束会话后清理。" }
                    MLabel { text: "使用远程模型时，相应文字或音频会发送到已配置服务。"; role: "supporting" }
                    MButton { text: "重置当前选择"; variant: "outlined"; enabled: !workspace.threadLocked; onClicked: learningViewModel.resetSession() }
                }
            }
        }
        ColumnLayout {
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                MButton { objectName: "openSpeechCompute"; text: "计算与加速"; variant: "outlined"; onClicked: shell.section = 2 }
            }
            LocalSpeechLibrary { Layout.fillWidth: true; Layout.fillHeight: true; onOpenCompute: shell.section = 2 }
        }
        SpeechComputePage { }
    }
    Connections { target: workspace; function onChanged() { if (workspace.settingsCategory !== "local") shell.section = 0 } }
}
