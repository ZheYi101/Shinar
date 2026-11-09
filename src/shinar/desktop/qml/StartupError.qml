import QtQuick
import QtQuick.Controls.Basic as Controls
import QtQuick.Layouts

Controls.ApplicationWindow {
    id: root
    objectName: "storageStartupErrorWindow"
    property string errorMessage: ""
    property string recoveryAdvice: ""
    property string configurationPath: ""
    title: qsTr("Shinar · 无法打开语音资源")
    visible: true
    width: 560
    height: 300
    minimumWidth: 360
    minimumHeight: 300
    color: "#F7F3E9"
    font.family: Qt.platform.os === "windows" ? "Microsoft YaHei UI" : "Noto Sans CJK SC"
    font.pixelSize: 14
    palette.windowText: "#3F382F"
    palette.text: "#3F382F"
    palette.button: "#56634F"
    palette.buttonText: "#FAF7EF"
    palette.highlight: "#56634F"
    palette.highlightedText: "#FAF7EF"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14

        Controls.Label {
            objectName: "storageStartupErrorMessage"
            Layout.fillWidth: true
            text: root.errorMessage
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            font.weight: Font.DemiBold
        }
        Controls.Label {
            objectName: "storageStartupRecoveryAdvice"
            Layout.fillWidth: true
            text: root.recoveryAdvice
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
        }
        Controls.TextArea {
            objectName: "storageStartupConfigurationPath"
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: root.configurationPath
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            background: Rectangle { color: "#EEE8DC"; radius: 4 }
            Accessible.name: qsTr("存储位置配置文件")
        }
        Controls.Button {
            objectName: "storageStartupExit"
            Layout.alignment: Qt.AlignRight
            Layout.minimumWidth: 76
            implicitHeight: 36
            text: qsTr("退出")
            onClicked: root.close()
        }
    }
}
