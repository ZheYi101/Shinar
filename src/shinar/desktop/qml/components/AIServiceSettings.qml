import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

ColumnLayout {
    id: panel
    required property var controller
    Layout.fillWidth: true
    spacing: 8
    MLabel { text: qsTr("AI API 连接"); role: "title" }
    MLabel { text: controller.sourceText; role: "supporting" }
    MLabel { text: qsTr("支持 OpenAI 兼容接口。保存后重新打开软件生效；当前对话使用启动时的配置。"); role: "supporting" }
    MLabel { text: qsTr("API 基础地址"); role: "label" }
    MTextField {
        objectName: "aiBaseUrlInput"; Layout.fillWidth: true
        placeholderText: qsTr("https://服务地址/v1"); Accessible.name: qsTr("API 基础地址")
        text: controller.baseUrl; onTextEdited: controller.baseUrl = text
        inputMethodHints: Qt.ImhUrlCharactersOnly
    }
    MLabel { text: qsTr("API Key"); role: "label" }
    MTextField {
        id: keyField; objectName: "aiApiKeyInput"; Layout.fillWidth: true
        echoMode: TextInput.Password; Accessible.name: qsTr("API Key")
        placeholderText: controller.hasApiKey ? qsTr("已有密钥，留空保留；输入新值可替换") : qsTr("输入服务提供的 API Key")
        onTextEdited: controller.setApiKey(text)
        inputMethodHints: Qt.ImhHiddenText | Qt.ImhNoPredictiveText
    }
    MLabel { text: qsTr("Windows 使用当前用户的系统加密保存密钥，安装包不含个人密钥。"); role: "supporting"; font.pixelSize: 12 }
    MButton {
        objectName: "testAiConnectionButton"
        text: controller.busy ? qsTr("正在读取模型…") : controller.modelsLoaded ? qsTr("刷新模型列表") : qsTr("读取模型列表")
        variant: "outlined"; enabled: !controller.busy
        onClicked: controller.testConnection()
    }
    MLabel { objectName: "aiConfigurationStatus"; visible: text.length > 0; text: controller.statusText; role: "supporting"; Accessible.role: Accessible.StaticText }
    MLabel { objectName: "aiConfigurationError"; visible: text.length > 0; text: controller.errorText; role: "supporting"; color: AppTheme.error; Accessible.role: Accessible.AlertMessage }
    MLabel { text: qsTr("推理模型"); role: "label" }
    MComboBox {
        objectName: "aiReasoningModelChoice"
        Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0
        model: controller.modelOptions
        enabled: !controller.busy && controller.modelOptions.length > 0
        currentIndex: controller.modelOptions.indexOf(controller.reasoningModel)
        displayText: controller.reasoningModel || (controller.modelsLoaded ? qsTr("选择材料准备和推理所用的模型") : qsTr("请先读取模型列表"))
        Accessible.name: qsTr("选择推理模型")
        onActivated: controller.reasoningModel = controller.modelOptions[currentIndex]
    }
    MLabel { text: qsTr("对话模型"); role: "label" }
    MComboBox {
        objectName: "aiDialogueModelChoice"
        Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0
        model: [qsTr("与推理模型相同")].concat(controller.modelOptions)
        enabled: !controller.busy && controller.modelOptions.length > 0
        currentIndex: controller.dialogueModel ? (controller.modelOptions.indexOf(controller.dialogueModel) < 0 ? -1 : controller.modelOptions.indexOf(controller.dialogueModel) + 1) : 0
        displayText: controller.dialogueModel || (controller.modelsLoaded ? qsTr("与推理模型相同") : qsTr("请先读取模型列表"))
        Accessible.name: qsTr("选择对话模型")
        onActivated: controller.dialogueModel = currentIndex === 0 ? "" : controller.modelOptions[currentIndex - 1]
    }
    MLabel { visible: text.length > 0; text: controller.modelSelectionHint; role: "supporting" }
    MLabel { text: qsTr("推理与对话是两个独立角色，可以使用同一个模型。连接检查只读取模型列表，不生成内容或发送学习材料。"); role: "supporting" }
    Flow {
        Layout.fillWidth: true; spacing: 8
        MButton { objectName: "saveAiConfigurationButton"; text: qsTr("保存配置"); enabled: controller.canSave; onClicked: controller.save() }
        MButton { objectName: "useAiEnvironmentButton"; visible: controller.hasSavedConfiguration; text: qsTr("恢复使用环境配置"); variant: "text"; onClicked: controller.useEnvironment() }
    }
    MLabel { visible: controller.restartRequired; text: qsTr("配置已变更。请退出并重新打开 Shinar 以启用。"); role: "supporting" }
    Connections { target: panel.controller; function onSecretCleared() { keyField.text = "" } }
}
