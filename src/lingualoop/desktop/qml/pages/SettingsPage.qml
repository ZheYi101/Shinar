import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"
import "../components"

ColumnLayout {
    id: shell
    property int section: 0
    spacing: AppTheme.gapMedium
    RowLayout {
        visible: shell.section !== 0
        Layout.fillWidth: true
        MButton { objectName: "speechSettingsBack"; text: "返回设置"; variant: "text"; onClicked: shell.section = 0 }
        MLabel { text: shell.section === 1 ? "语音模型" : "计算与加速"; role: "title" }
    }
    StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: shell.section
ScrollView {
    id: page
    objectName: "settingsOverview"
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: page.availableWidth
        spacing: AppTheme.sectionGap
        MLabel { text: "按你的节奏来"; role: "headline" }
        MCard {
            MLabel { text: "外观"; role: "title" }
            PreferenceChoice { label: "主题"; preferenceKey: "themeMode"; choices: ["跟随系统", "浅色", "深色"]; values: ["system", "light", "dark"] }
            Switch { text: "减少动效"; checked: learningViewModel.preferences.reducedMotion; onToggled: learningViewModel.preferences.setValue("reducedMotion", checked) }
        }
        MCard {
            MLabel { text: "新对话的学习偏好"; role: "title" }
            PreferenceChoice { label: "目标语言"; preferenceKey: "targetLanguage"; choices: ["日语", "英语", "中文", "法语", "德语", "西班牙语"]; values: ["japanese", "english", "chinese", "french", "germany", "spanish"] }
            PreferenceChoice { label: "母语"; preferenceKey: "nativeLanguage"; choices: ["中文", "英语", "日语", "法语", "德语", "西班牙语"]; values: ["chinese", "english", "japanese", "french", "germany", "spanish"] }
            PreferenceChoice { label: "难度"; preferenceKey: "difficulty"; choices: ["暂不确定", "A1", "A2", "B1", "B2", "C1", "C2"]; values: ["unknown", "A1", "A2", "B1", "B2", "C1", "C2"] }
            PreferenceChoice { label: "反馈时机"; preferenceKey: "feedbackTiming"; choices: ["结束后集中反馈", "本轮不纠错"]; values: ["end", "off"] }
            MLabel { visible: learningViewModel.preferences.feedbackTiming === "immediate"; text: "原有即时反馈偏好在本阶段延后到结束，保持讨论流畅。"; role: "supporting" }
            PreferenceChoice { label: "纠错强度"; preferenceKey: "correctionIntensity"; choices: ["轻量", "适中", "详细"]; values: ["low", "medium", "high"] }
        }
        MCard {
            MLabel { text: "音频设备"; role: "title" }
            MLabel { text: "麦克风"; role: "label" }
            ComboBox { Layout.fillWidth: true; implicitHeight: 48; model: learningViewModel.inputDevices; textRole: "name"; Accessible.name: "麦克风"; onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, false) }
            MLabel { text: "播放设备"; role: "label" }
            ComboBox { Layout.fillWidth: true; implicitHeight: 48; model: learningViewModel.outputDevices; textRole: "name"; Accessible.name: "播放设备"; onActivated: learningViewModel.selectAudioDevice(model[currentIndex].id, true) }
        }
        MCard {
            MLabel { text: "语音连接"; role: "title" }
            MLabel { text: "文本服务：" + learningViewModel.providerLabel; role: "supporting" }
            MLabel { text: learningViewModel.speechStatus; role: "supporting" }
            MLabel { text: "语音模型按语言选择；计算与加速设置 CPU/GPU、运行环境与资源预算。远程连接从本地环境配置读取。"; role: "supporting" }
            MButton { objectName: "openSpeechCompute"; text: "计算与加速"; variant: "outlined"; onClicked: shell.section = 2 }
            MButton { objectName: "openLocalSpeechLibrary"; text: "语音模型"; variant: "outlined"; onClicked: shell.section = 1 }
        }
        MCard {
            MLabel { text: "本地数据"; role: "title" }
            MLabel { text: "材料、确认后的消息和复习项保存在本地 SQLite。录音只作临时处理，结束会话后清理。"; role: "supporting" }
            MButton { text: "重置当前选择"; variant: "outlined"; enabled: !learningViewModel.busy; onClicked: learningViewModel.resetSession() }
        }
        Item { Layout.preferredHeight: 16 }
    }
}

        LocalSpeechLibrary { onOpenCompute: shell.section = 2 }
        SpeechComputePage { }
    }
}
