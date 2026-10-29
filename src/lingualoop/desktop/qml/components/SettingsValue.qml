import QtQuick
import QtQuick.Layouts

SettingsRow {
    id: root
    property string value: ""
    MLabel {
        text: root.value
        role: "supporting"
        Layout.fillWidth: root.compact
        Layout.preferredWidth: root.compact ? root.width : Math.min(440, root.width*0.6)
        horizontalAlignment: root.compact ? Text.AlignLeft : Text.AlignRight
    }
}
