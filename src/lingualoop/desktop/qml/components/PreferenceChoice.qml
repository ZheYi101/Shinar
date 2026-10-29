import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

SettingsRow {
    id: root
    property string preferenceKey: ""
    property var choices: []
    property var values: []
    MComboBox {
        objectName: "preference-" + root.preferenceKey
        Layout.fillWidth: root.compact
        Layout.preferredWidth: 220
        model: root.choices; Accessible.name: root.label
        currentIndex: Math.max(0, root.values.indexOf(learningViewModel.preferences[root.preferenceKey]))
        onActivated: learningViewModel.preferences.setValue(root.preferenceKey, root.values[currentIndex])
    }
}
