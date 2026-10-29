import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../design"

GridLayout {
    id: root
    property string label: ""
    property string preferenceKey: ""
    property var choices: []
    property var values: []
    columns: width < 450 ? 1 : 2
    columnSpacing: 24; rowSpacing: 10
    Layout.fillWidth: true
    MLabel { text: root.label; role: "label"; Layout.minimumWidth: 120 }
    ComboBox {
        Layout.fillWidth: root.columns === 1
        Layout.preferredWidth: root.columns === 1 ? -1 : 220
        implicitHeight: 38
        model: root.choices; Accessible.name: root.label
        currentIndex: Math.max(0, root.values.indexOf(learningViewModel.preferences[root.preferenceKey]))
        onActivated: learningViewModel.preferences.setValue(root.preferenceKey, root.values[currentIndex])
    }
}
