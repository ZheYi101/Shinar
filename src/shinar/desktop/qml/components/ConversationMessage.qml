import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

ColumnLayout {
    id: root
    required property var message
    readonly property bool userMessage: message.role === "user"
    property bool copied: false
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    Layout.maximumWidth: Infinity
    Layout.preferredWidth: parent.width
    spacing: 2
    HoverHandler { id: messageHover }
    TextMetrics {
        id: measure
        text: root.message.content
        font: body.font
    }
    Rectangle {
        id: bubble
        readonly property int inset: root.userMessage ? 14 : 0
        Layout.fillWidth: !root.userMessage
        Layout.alignment: root.userMessage ? Qt.AlignRight : Qt.AlignLeft
        Layout.preferredWidth: root.userMessage ? Math.min(root.width * 0.86, Math.max(72, measure.advanceWidth + 28)) : root.width
        implicitHeight: body.contentHeight + inset * 2
        radius: 14
        color: root.userMessage ? AppTheme.surfaceContainerLow : "transparent"
        TextEdit {
            id: body
            objectName: "messageBody-" + root.message.id
            x: bubble.inset; y: bubble.inset
            width: bubble.width - bubble.inset * 2
            height: contentHeight
            text: root.message.content
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            textFormat: TextEdit.PlainText
            color: AppTheme.colorOnSurface
            selectionColor: AppTheme.primaryContainer
            selectedTextColor: AppTheme.colorOnPrimaryContainer
            font.family: learningViewModel.preferences.targetLanguage === "japanese" ? AppTheme.japaneseFont : AppTheme.uiFont
            font.pixelSize: 16
            Accessible.name: (root.userMessage ? qsTr("我：") : qsTr("伙伴：")) + text
        }
    }
    RowLayout {
        Layout.alignment: root.userMessage ? Qt.AlignRight : Qt.AlignLeft
        spacing: 4
        opacity: messageHover.hovered || copyButton.activeFocus || root.copied ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: AppTheme.motionFast } }
        MIconButton {
            id: copyButton
            objectName: "copyMessage-" + root.message.id
            symbol: "copy"
            label: root.copied ? qsTr("已复制") : qsTr("复制消息")
            implicitWidth: 28; implicitHeight: 28; padding: 6
            onClicked: { body.selectAll(); body.copy(); body.deselect(); root.copied = true; copiedTimer.restart() }
        }
        MLabel { visible: root.copied; text: qsTr("已复制"); font.pixelSize: 11; role: "supporting" }
    }
    Timer { id: copiedTimer; interval: 1400; onTriggered: root.copied = false }
}
